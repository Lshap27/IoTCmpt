# IoTCmpt 队友答辩与演示手册

本源稿由 `tools/generate-readme-easy.py` 转换为根目录 `README_easy.docx`。`[[PAGEBREAK]]` 表示有意分页；图片路径相对项目根目录，缺图时生成器会放置说明占位符。

[[PAGEBREAK]]
## 1. 先记住这一句话

IoTCmpt 是一个“会感知、会执行、能分析、可追踪”的宿舍环境 AIoT 系统：ESP32-S3 负责现场实时工作，Gateway 负责可靠通信和数据，AI Worker 负责慢速智能分析，MCP 负责规范地调用工具，Web 控制台负责让人看懂并操作。

> [!IMPORTANT] 答辩时不要说“大模型直接控制硬件”。正确说法是：大模型提出工具调用，Worker 经 MCP 进入统一命令服务，固件仍可因能力、人工优先或安全联锁拒绝。

- 烟雾报警不等待网络和大模型。
- 人工命令不等待大模型。
- AI 失败不会阻塞遥测和人工控制。
- 每条操作都能用 `trace_id` 查完整链路。

[[PAGEBREAK]]
## 2. 阅读路线与答辩目录

建议先读“总体架构、五个角色、三条典型流程”，再读“可靠性与安全”，最后读“演示、上板、排障和问答”。

1. 系统全景与职责边界：第 3～7 节。
2. 固件运行逻辑：第 8～12 节。
3. Gateway、Worker、MCP 与数据库：第 13～24 节。
4. 控制台、诊断页、启动面板与模拟器：第 25～29 节。
5. 五条关键时序：第 30～34 节。
6. 演示、上板、测试、扩展与答辩：第 35～44 节。

本手册不是代码清单，而是“为什么这样设计、各部分怎样协作、出了问题怎样定位”的讲解稿。

[[PAGEBREAK]]
## 3. 整个系统长什么样

系统可以理解为一栋有“现场人员、总控室、分析员和工具窗口”的智能宿舍：

- ESP32-S3 像现场值守人员，读传感器、驱动舵机/灯/报警器，并执行安全规则。
- Gateway 像总控室，接收 MQTT、保存数据、分发命令和实时事件。
- AI Worker 像分析员，异步领取任务，向大模型提问并调用 MCP 工具。
- MCP 像有权限控制的工具窗口，所有读写操作都要走同一业务规则。
- Web 像控制台，人通过它查看状态、下命令、配置巡检和排障。

数据库不只是“存历史”，还保存任务、租约、Outbox、实时事件和 trace，因此重启后任务不会凭空消失。

[[PAGEBREAK]]
## 4. 五个角色分别负责什么

### 固件
采样、融合、执行器、本地烟雾规则、人工优先、安全联锁、ACK 幂等。

### Gateway
HTTP/WebSocket/MQTT/MCP Server、设备快照、命令状态机、Outbox、诊断时间线。

### AI Worker
模型调用、MCP Host、事件分析、巡检、报告、任务重试和取消。

### Web
状态展示、人工操作、自动化策略、AI 任务历史和诊断；不保存业务真相。

### PostgreSQL/TimescaleDB
设备数据、历史遥测、命令、AI Run、工具调用、报告、可靠队列和审计。

> [!NOTE] 一个模块只做自己擅长的事，问题发生时才容易判断是“硬件、通信、业务、模型还是界面”。

[[PAGEBREAK]]
## 5. 这些角色怎样耦合

新架构保留必要耦合，消除危险耦合：

- 固件和 Gateway 只通过版本化 MQTT v2 契约耦合。
- Web 和 Gateway 只通过 `/api/v1` 与 WebSocket v2 耦合。
- Worker 和 Gateway 通过数据库任务及内部 MCP 耦合。
- 大模型只看提示词和工具定义，不拿 MQTT、数据库或固件连接信息。
- 模拟器和真实固件使用同一命令目录、行为阈值和消息状态机。

所谓“低耦合”不是完全没有联系，而是联系发生在清晰、可测试、可版本化的接口上。

[[PAGEBREAK]]
## 6. 快路径与慢路径为什么必须分开

快路径包括遥测、人工命令、烟雾安全和固件执行，它们需要稳定、可预测，不能等待几十秒的大模型。

慢路径包括环境分析、巡检、报告和视觉判断，可以排队、重试、取消，也允许模型超时。

如果把两条路径绑在一起，大模型卡住就可能导致界面无响应甚至控制失效。现在 AI 创建接口立即返回 `202 queued`，Worker 在后台继续处理；Gateway 仍可接收遥测和人工命令。

答辩关键词：**实时闭环本地化，智能分析异步化，故障影响隔离化。**

[[PAGEBREAK]]
## 7. 契约为什么是架构的骨架

`contracts/` 是固件、后端、模拟器和前端共同遵守的规则：

- `commands.json`：命令、参数、来源、TTL、安全等级和 AI 权限。
- `mqtt-envelope.schema.json`：MQTT v2 公共信封。
- `device-capabilities.schema.json`：设备实际能力。
- `firmware-behavior.json`：融合阈值、队列长度、ACK 缓存和执行周期。
- `websocket-events.json`：实时事件类型。

生成器输出固件 C 头文件、服务端 Python 目录和模拟器常量。CI 检查漂移，防止“后端以为能执行，固件却没有实现”。

[[PAGEBREAK]]
## 8. 固件的一次主循环

固件启动后先做配置预检，再初始化状态、传感器、执行器、摄像头、Wi-Fi、SNTP 和 MQTT。运行期间存在多条独立任务：

1. 采样任务读取原始传感器。
2. 融合规则计算空气质量、通风建议和原因。
3. 安全任务持续处理烟雾和报警。
4. 命令任务从长度为 4 的队列取命令并执行。
5. 执行器任务把“目标状态”真正施加到舵机、LED 等硬件。
6. 通信任务发布状态、能力、遥测、事件和 ACK。

`app_main` 只负责组装模块，不把所有硬件逻辑塞进一个巨大函数。

[[PAGEBREAK]]
## 9. 从原始传感器到空气结论

场景或硬件只产生温度、湿度、TVOC、HCHO、eCO2、烟雾和光照等原始值。融合算法再计算：

- `air_quality`：good、watch 或 alert。
- `recommend_open_window`：是否建议通风。
- `alarm_enabled`：本地报警源是否有效。
- `reason`：为什么得到这个结论。

这一步在固件本地完成，模拟器也使用相同阈值。大模型可以解释趋势和给出更综合建议，但不能替代固定的烟雾安全规则。

[[PAGEBREAK]]
## 10. 烟雾安全为什么最特殊

烟雾出现时，本地安全循环直接开启报警并发布状态，不需要 MQTT、Gateway、Worker 或 LLM 存活。

- `alarm.silence` 只在 10～600 秒内临时屏蔽烟雾报警声，不删除烟雾事实。
- 静音到期而烟雾仍在时，报警自动恢复。
- AI 不获得关闭报警或改变控制优先级的工具。
- 人工优先也不能绕过不可妥协的安全联锁。

答辩时可概括为：**AI 有建议权和有限执行权，固件有最终否决权。**

[[PAGEBREAK]]
## 11. 一条命令在固件里怎样执行

固件按固定顺序处理命令：

1. 验证 MQTT v2 信封、设备 ID、命令 ID、来源、参数和 `expires_at`。
2. 如果命中最近 16 个终态缓存，直接重放原结果。
3. 检查编译能力、人工优先和安全联锁。
4. 放入长度为 4 的队列并立即回复 `accepted`。
5. 独立执行任务驱动状态/硬件，回复 `executed`、`rejected` 或 `failed`。

`accepted` 和终态 ACK 使用不同 `message_id`，但都指向同一个 `command_id`。

[[PAGEBREAK]]
## 12. 固件联网、时间和重连

Wi-Fi 断开时固件立即清除连接状态，避免界面误认为设备在线。MQTT 重连后重新发布 retained 状态和能力，Gateway 因此能恢复设备真实能力。

SNTP 用来获得可信系统时间。时间可信时严格判断命令是否过期；尚未同步时会记录“未进行 TTL 可信校验”的诊断，而不是假装已经验证。

本机地址必须写成电脑局域网 IP；对 ESP32 来说，`localhost` 指设备自己，不是电脑。

[[PAGEBREAK]]
## 13. Gateway 内部分成哪些层

- Domain：纯业务概念和规则。
- Application：提交命令、查询快照、创建 AI Run、诊断等用例。
- Ports：应用需要的数据库、MQTT、LLM、MCP、时钟和 ID 接口。
- Adapters：FastAPI、SQLAlchemy、aiomqtt、MCP SDK、模型客户端等实现。

HTTP 路由、MQTT 回调和 MCP 工具都是“适配器”，它们不能各写一套业务逻辑。三者最终调用同一 Application Service，所以在线界面、外部 MCP 和 AI 都接受同样的能力、TTL、频率和安全检查。

[[PAGEBREAK]]
## 14. 遥测进入 Gateway 后发生什么

MQTT 入站首先检查 v2 信封，并按 `(device_id, topic, message_id)` 去重 QoS 1 重发。随后：

1. 更新设备在线状态和最后见到时间。
2. 写入 TimescaleDB 遥测历史。
3. 更新设备快照/数字孪生。
4. 必要时生成设备事件或持久 AI Run。
5. 写入 realtime event，由 Gateway Relay 推到 WebSocket。

数据库事务失败会先回滚，再记录 `system.error`，不会在损坏事务上继续写。

[[PAGEBREAK]]
## 15. 后端命令状态机

人工、AI、外部 MCP 和固件规则的命令统一进入：

`created -> queued -> published -> accepted -> executed/rejected/failed`

还可能进入 `expired` 或 `timed_out`。命令创建与 Outbox 记录在同一数据库事务内，保证“数据库说存在但从未安排发布”与“先发 MQTT 后来不及存审计”都不会发生。

幂等键按 `(device_id, source, idempotency_key)` 隔离，不同设备和不同入口不会错误复用同一命令。

[[PAGEBREAK]]
## 16. Outbox 与 MQTT QoS 1 怎样配合

Outbox 是数据库里的“待发送箱”。发布器领取行、发到 MQTT、成功后标记完成；失败会指数退避重试，耗尽后留下明确错误和 trace。

QoS 1 可能重复投递，所以系统不假设“只发一次”：

- Outbox 通过租约防止多个发布器同时拥有同一行。
- 固件按 `command_id` 幂等，不重复动作。
- Gateway 按 `message_id` 去重入站 ACK。
- Web 按 `event_id` 去重实时事件。

可靠性来自多层共同保证，而不是单点侥幸。

[[PAGEBREAK]]
## 17. AI Worker 为什么独立进程

大模型响应慢、可能超时，还可能进行多轮工具调用。如果放在 Gateway 请求进程里，会拖累 HTTP、MQTT 和 WebSocket。

Worker 从 PostgreSQL 领取持久 `ai_runs`，状态包括 queued、running、waiting_model、calling_tool、waiting_device，以及 succeeded、failed、cancelled、skipped。

Worker 死亡后租约到期，任务可被另一个 Worker 恢复；默认最多尝试 3 次。报告、工具调用和硬件命令都有稳定幂等标识，恢复不能制造重复副作用。

[[PAGEBREAK]]
## 18. 租约 fencing 解决什么竞态

只使用 `SKIP LOCKED` 还不够：旧 Worker 可能暂停 100 秒，租约过期后新 Worker 接手，旧 Worker 又醒来并提交结果。

因此每次领取都生成新的 `lease_token`。续租、模型/MCP 副作用前检查、完成、失败和重试都必须匹配：任务 ID + owner + token。

旧 Worker 的 token 已失效，即使恢复也不能写成功或继续控制设备。这叫 fencing（栅栏），是“允许 Worker 安全扩容”的关键条件。

[[PAGEBREAK]]
## 19. MCP 到底是什么

MCP 可以理解为“大模型工具的标准插座”。模型只返回想调用的工具和参数，Worker 作为 Host 决定是否允许，并通过 MCP Client 调用 Gateway `/mcp`。

第一批工具包括设备列表、快照、历史、事件、能力、命令查询、执行安全命令和创建通知。每个工具统一返回 `ok、trace_id、data、error`。

工具不直接发布 MQTT，而是进入统一 Application Service。这样 MCP 是规范入口，不是绕过架构的后门。

[[PAGEBREAK]]
## 20. MCP 权限和安全边界

- 内部 Token 只供 Worker 与 Gateway 使用，不进入前端、日志或诊断响应。
- 外部 MCP 默认关闭；开启时只读 Token 与控制 Token 必须不同。
- Token 使用常量时间比较，并检查 Host、Origin 和速率限制。
- `report`、`vision` 只获得只读工具。
- `decision`、`patrol` 才能看到 `window.*`、`led.*`、`voice.speak`、`display.message`。
- 关闭/静音报警、改变优先级等高风险能力不暴露给 AI。

任何控制仍要经过在线、能力、参数、TTL、频率和固件安全联锁。

[[PAGEBREAK]]
## 21. 四类 AI Run

### decision
针对当前状态做一次判断，可调用安全控制工具。

### patrol
按每设备策略周期检查；有变化或到强制间隔才调用模型。

### report
读取历史聚合数据，生成小时/日报/周报等解释，只读。

### vision
基于最新图像与本地感知结果做视觉分析，只读。

所有类型都先持久化再异步运行。Mock AI 也走相同的 Run、MCP、命令和 ACK 闭环，而不是前端假数据。

[[PAGEBREAK]]
## 22. 周期巡检怎样省费用

巡检默认关闭。启用后每到周期先读取最新快照并计算指纹：

- 空气等级、烟雾、人体、坐姿、窗口、报警、LED、优先级变化会触发。
- 温度至少变化 1℃、湿度 5%、eCO2 100 ppm、TVOC 50 ppb、HCHO 10 μg/m³ 才算有效变化。
- 未变化则记录 `skipped/unchanged`，不产生模型费用。
- 即使长期稳定，也在默认 3600 秒强制间隔后完整分析一次。

同一设备只运行一个巡检；后续触发合并，避免任务风暴。

[[PAGEBREAK]]
## 23. 报告与视觉分析怎样工作

报告通过 MCP 读取指定起止时间和 bucket 的历史，Gateway 真正聚合连续指标，并保留输入时区后统一转换 UTC。模型不能凭空补齐缺失样本。

图像上传先由本地 MediaPipe 人体/姿态模型产生可复核结构化结果，再排队 vision Run；Gateway 不在上传请求中同步等待云模型。

报告与视觉只读，因此即使模型误判也不会直接驱动硬件。需要控制时，应创建 decision/patrol 并接受完整安全检查。

[[PAGEBREAK]]
## 24. 数据库里保存什么

业务数据：设备、遥测、事件、图片、姿态、通知、命令和命令事件。

架构数据：设备能力、数字孪生、自动化策略、AI Run、工具调用、AI 报告。

可靠性数据：MQTT Outbox、Realtime Events、MQTT Inbox 幂等、Worker 心跳、运行租约。

诊断数据：`trace_events` 把 HTTP、AI、MCP、Outbox、MQTT、ACK 和 WebSocket 串起来。

TimescaleDB 主要优化遥测时间序列；普通 PostgreSQL 表承担事务和任务协调。

[[PAGEBREAK]]
## 25. 主控制台怎么看

![主控制台](docs/assets/readme-easy/dashboard-live.png)

主控制台保留环境卡片、实时趋势、摄像头、通知和事件流。AI 区分为最近任务、任务历史和自动化策略；命令区展示完整状态与来源。

读图时先看顶部“设备在线”，再看环境指标，随后看趋势与 AI 结论。AI 结果中的 trace 文本可进入诊断时间线。界面只是数据消费者，权威状态仍来自 Gateway/数据库。

[[PAGEBREAK]]
## 26. 诊断页怎么看

![诊断页](docs/assets/readme-easy/diagnostics-live.png)

`/diagnostics` 只显示非秘密信息：数据库、MQTT、Worker、MCP、迁移状态，AI/Outbox/实时事件计数，Worker 心跳和设备能力。

历史 Worker 可能保留在数据库中；只有 45 秒内心跳才标记健康。输入 `trace_id` 后，下方按时间展示完整执行链，适合答辩演示“为什么架构更容易定位 Bug”。

[[PAGEBREAK]]
## 27. 启动配置面板怎么看

![启动配置面板](docs/assets/readme-easy/startup-panel.png)

面板只监听 `127.0.0.1:8765`，包含环境中心、项目配置、服务控制、固件配置、固件操作和数据工具。写操作必须带随机 Panel Token，秘密只显示“已配置”。

服务卡能看到 Gateway、Web、MQTT、数据库、Worker、迁移和固件模拟器；模拟器还显示场景、Boot ID、遥测/命令数、窗口、LED、报警、优先级和最近命令。图中顶部地址在 Word 中被裁掉，避免展示本机网络信息。

[[PAGEBREAK]]
## 28. 固件行为模拟器是什么

它不是网页假数据，也不是 QEMU，而是电脑上运行的轻量固件状态机：

- 使用真实 MQTT v2 和 HTTP 图片上传。
- 使用真实命令队列、accepted/终态 ACK 和 NVS 重放。
- 独立 100 ms 安全循环，不受 2 秒遥测周期影响。
- MQTT 断开时继续执行已 accepted 命令，重连后补发终态 ACK。
- 模拟 NVS 保留优先级和最近终态；重启生成新 Boot ID，易失执行器恢复默认。

它适合软件联调和演示，不模拟电气故障、传感器损坏或机械卡顿。

[[PAGEBREAK]]
## 29. 四种模拟场景

### normal
指标正常，验证稳定遥测、图片、无动作 AI 结论。

### air-watch
指标进入关注区间，验证融合等级和趋势解释。

### air-alert
指标超过告警阈值，验证通风建议、AI/MCP 开窗和 ACK 闭环。

### smoke
空气指标可正常但烟雾有效，验证本地报警、静音、恢复和云端故障隔离。

场景只改变原始传感器值，不直接写死 `air_quality` 或报警结果。

[[PAGEBREAK]]
## 30. 人工命令时序

1. 用户在 Web 点击“开灯/开窗”。
2. Web 向 `/api/v1/.../commands` 提交，Gateway 返回 `202`。
3. Gateway 在一个事务中保存 Command 与 Outbox。
4. Outbox 发布 MQTT command，状态变为 published。
5. 固件验证后回复 accepted。
6. 执行器完成后回复 executed，或因策略/安全回复 rejected。
7. Gateway 保存 ACK，WebSocket 推送，界面更新终态。

这条路径完全不调用大模型，模型慢或挂掉不影响人工控制。

[[PAGEBREAK]]
## 31. AI 控制时序

1. 用户或事件创建 decision/patrol Run，立即得到 `202 queued`。
2. Worker 用租约领取任务，调用模型。
3. 模型返回 `device_get_snapshot` 或 `device_execute_command` 工具调用。
4. Worker 经内部 MCP 调用 Gateway；Gateway 重新做权限和命令校验。
5. 命令经 Outbox、MQTT 到固件。
6. Worker 进入 `waiting_device`，读取命令直到终态。
7. 设备拒绝表示“分析成功但动作失败”；模型/MCP/传输异常才令 Run 失败。

整条链共享一个 `trace_id`。

[[PAGEBREAK]]
## 32. 烟雾安全时序

1. MQ-2/场景出现烟雾边沿。
2. 固件 100 ms 安全循环立即开启本地报警。
3. 固件发布事件和遥测；Gateway 存库并推送界面。
4. 即使 Worker、LLM 或互联网不可用，报警仍持续。
5. 人工可在允许范围内临时静音；静音不会把 `smoke_detected` 改成 false。
6. 静音到期且烟雾未清除，报警恢复；烟雾清除后发布一次恢复边沿。

重连不会重复制造同一烟雾 transition 事件。

[[PAGEBREAK]]
## 33. 巡检和报告时序

巡检调度器由数据库租约选出一个持有者。到期后先算快照指纹；未变化就 `skipped`，有变化或达到强制间隔才创建模型调用。多 Worker 都可执行普通 Run，但只有一个调度器生成周期任务。

报告读取历史时间范围与 bucket，通过只读 MCP 获取聚合数据。输出写入 `ai_reports`，按 Run 幂等更新；Worker 重试不会产生两份同一报告。

两者都通过 Realtime Event 让独立 Worker 的状态进入 Gateway WebSocket。

[[PAGEBREAK]]
## 34. trace 排障方法

从界面、HTTP 响应头、AI Run、MCP 返回或日志拿到 `trace_id`，查看最后出现在哪一段：

- 无 AI Run：前端请求或参数校验。
- 一直 queued：Worker 心跳、租约或数据库。
- waiting_model：模型地址、Key、超时或 Provider。
- tool failed：MCP 权限、参数或应用用例。
- queued/published：Outbox、Broker、设备在线和 Topic。
- accepted 无终态：固件执行任务、联锁或重启。
- 终态但 UI 旧：Realtime Relay、WebSocket 或查询缓存。

迟到 ACK 记录为 `late_device_ack`，主状态仍保持 timed_out。

[[PAGEBREAK]]
## 35. 推荐启动流程

1. 双击 `启动配置面板.cmd`，在环境中心检查 Docker、Node、Python 和 ESP-IDF。
2. 项目配置选择“固件模拟器 + 本地 Mock AI”。
3. 预览配置差异，应用后只重启受影响服务。
4. 服务控制启动 Docker 演示栈，等待数据库、MQTT、Gateway、Worker 和 Web 就绪。
5. 启动/应用模拟器配置，先选 normal。
6. 打开 `http://localhost:3000`，再打开 `/diagnostics`。
7. 演示命令、AI Run、场景切换和 trace。

在线模型演示应在离线闭环通过后再启用。

[[PAGEBREAK]]
## 36. 五分钟答辩演示脚本

### 第 1 分钟：架构
指出固件、Gateway、Worker、MCP、Web 五个角色，以及快慢路径隔离。

### 第 2 分钟：正常数据
展示 normal 遥测、趋势、设备能力和周期图片。

### 第 3 分钟：人工与 AI
执行一次人工 LED 命令，再切 air-alert 创建 AI decision，观察 accepted 到 executed。

### 第 4 分钟：安全
切 smoke，强调本地报警不等待模型，演示有限静音与恢复。

### 第 5 分钟：诊断
点 trace，展示 HTTP、AI、MCP、Outbox、MQTT、ACK、WebSocket 时间线。

[[PAGEBREAK]]
## 37. 上板前配置预检

必须先确认准确模组、Flash、PSRAM、USB 模式和接线图。面板会阻止明显冲突：

- 任意两个已启用功能使用同一 GPIO。
- 原生 USB 与 GPIO19/20 复用。
- 八线 PSRAM 与 GPIO35～37 复用。

安全默认不会自动开启全部硬件，模拟传感器默认关闭。`full-hardware.defaults` 只能说明所有模块能编译链接，不能直接烧录。OV2640 保留现有 PWDN-only、`pin_xclk=-1`，不要在没有原理图时猜测 XCLK。

[[PAGEBREAK]]
## 38. 真机验收清单

1. 外设全关时验证 USB/串口、启动日志和复位。
2. 验证供电、电平、共地和舵机独立供电能力。
3. 连接 Wi-Fi、SNTP、MQTT，核对 retained 状态与能力。
4. 每次只增加一类传感器或执行器，观察真实 GPIO。
5. 验证 JPEG、PSRAM 和 OV2640 时序。
6. 验证每条命令 accepted/终态、TTL、重复 command_id。
7. 重启 EMQX/Gateway，观察固件自动重连。
8. 断开云端服务，验证烟雾安全仍工作。
9. 验证人工优先、AI 拒绝与执行器机械动作。

每一项要记录“通过/失败/未测”，不能用编译成功替代。

[[PAGEBREAK]]
## 39. 本轮已经验证什么

- 服务端 Ruff、格式、mypy 和分批 pytest：78 项通过。
- 前端 lint、格式、typecheck、build；Playwright 9 项通过、2 项按未启用场景跳过。
- PostgreSQL + EMQX + 两个 Worker：任务唯一领取与多次 AI 闭环成功。
- Mock AI -> MCP -> MQTT -> 模拟固件 ACK 完整成功。
- normal、air-watch、air-alert、smoke 模拟场景和静音/恢复。
- ESP-IDF 5.5.2 默认安全镜像与全功能编译检查都成功，分区仍有余量。
- 契约生成、OpenAPI 和前端客户端无漂移。

这些结论针对当前软件版本和本机测试环境。

[[PAGEBREAK]]
## 40. 本轮明确没有验证什么

本轮没有真实 ESP32-S3 开发板，因此以下均为“未验证”，不能在答辩中说已经通过：

- USB/JTAG 或 USB-UART 枚举与烧录。
- 实际 GPIO 接线、Flash/PSRAM 型号与供电稳定性。
- OV2640 时钟、帧同步、图片质量和长时间运行。
- ST7735 显示、SYN6288 语音、MQ-2/SHT30/TVOC301 电平与标定。
- SG90 舵机角度、堵转、电源噪声和机械行程。
- 真实网络丢包、电磁干扰和长时间现场稳定性。

模拟器证明架构对接，真机负责最终电气验收。

[[PAGEBREAK]]
## 41. 怎样扩展新功能

### 新传感器
加驱动与字段，决定是否需要历史列，更新契约/序列化/指纹和前端图表。

### 新执行器命令
先改 `commands.json`，生成目录，实现固件 handler 和能力依赖，再补应用校验、MCP 权限、UI 与 ACK 测试。

### 新 MCP 工具
设计小而明确的资源工具，调用 Application Service，返回统一结构，分配读写/AI 权限并记录 trace。

### 新模型 Provider
只在 Worker 的 LLM Adapter 处理差异，不让 Domain、MCP 或固件依赖 Provider SDK。

### 新板型
从安全配置开始，补预检规则，隔离构建后再分模块真机验证。

[[PAGEBREAK]]
## 42. 常见答辩问题（架构）

### 为什么不让大模型直接发 MQTT？
因为会绕过能力、参数、TTL、频率、安全联锁、幂等和审计。MCP 进入统一命令服务更规范。

### 为什么不用微服务、Redis、Celery？
比赛/单网关规模下，模块化单体更易部署；PostgreSQL 已承担持久任务、租约和 Outbox。Worker 独立后最慢部分已隔离。

### 为什么 Worker 能扩容？
领取用 `SKIP LOCKED`，所有副作用又受 owner + lease_token fencing 约束，旧 Worker 不能越权完成。

### AI 会不会造成危险？
AI 只见安全命令；Gateway 再校验；固件拥有最终联锁与拒绝权。

[[PAGEBREAK]]
## 43. 常见答辩问题（演示与可靠性）

### 模拟器是不是假数据页面？
不是。它通过真实 MQTT/HTTP 连接真实 Gateway、数据库、Worker、MCP 和 Web，只把物理传感器/执行器换成行为状态机。

### 网络断开后 accepted 命令怎么办？
模拟器/固件执行任务独立于 MQTT；终态 ACK 可缓存，重连后补发。真实固件用 NVS 重放近期终态。

### 模型超时怎么办？
Run 失败或重试，但遥测、人工命令和烟雾本地规则继续工作。

### 为什么 trace 有价值？
它把跨进程、跨协议的一次操作串成时间线，能明确最后成功阶段和责任模块。

[[PAGEBREAK]]
## 44. 术语表与最后复述

- MQTT：设备与 Gateway 的轻量消息协议。
- retained：Broker 保存最新状态，新订阅者立即收到。
- ACK：命令接收或执行结果确认。
- Outbox：数据库中的可靠待发送队列。
- 幂等：同一请求重复到达也只产生一次效果。
- Lease：有期限的任务所有权。
- Fencing：用新 token 阻止旧持有者继续产生副作用。
- MCP：大模型调用工具的标准协议边界。
- AI Run：可排队、重试、取消、追踪的持久 AI 任务。
- Device Twin：服务器保存的设备报告/期望状态。
- trace_id：贯穿一次操作全链路的排障编号。

最后一句：**现场安全由固件保证，可靠协作由 Gateway 和数据库保证，智能分析由独立 Worker + MCP 保证，用户理解与操作由双面板保证。**
