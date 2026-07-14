# IoTCmpt AIoT 工作区

这是一个面向比赛的 ESP32-S3 AIoT 工作区，系统按协议优先的方式组织：

```text
ESP32-S3 固件 <-> MQTT v2 <-> FastAPI 应用核心 <-> HTTP/WS v1 <-> Next.js 控制台
                                      ^
                                      +-> 持久 AI Worker <-> MCP 工具 <-> 云端大模型
```

仓库只保留 AIoT 主线。MQTT 是遥测与控制的主干；HTTP 用于健康检查、仪表盘 API 和 JPEG 图像上传。HTTP/WebSocket 契约有单一事实来源：`server/openapi.json`，前端 API 客户端由它生成。

## 架构

- `firmware/esp32s3/`：面向 ESP32-S3-DevKitC-1 的 ESP-IDF（v5.5.2）固件。
- `server/`：FastAPI 模块化单体——按 domain/application/ports/adapters 分层，负责 MQTT、HTTP/WebSocket、MCP Streamable HTTP、持久 AI 任务、事务 outbox 和 TimescaleDB。
- `web/`：Next.js 15 + React 19 实时设备控制台——Tailwind CSS v4、shadcn/ui、TanStack Query，API 客户端由 OpenAPI 生成（`@hey-api/openapi-ts`）。
- `infra/`：部署说明和服务配置。
- `docs/`：架构、协议和数据模型契约。

## 协议入口

MQTT Topic：

- `devices/{device_id}/status`
- `devices/{device_id}/capabilities`
- `devices/{device_id}/telemetry`
- `devices/{device_id}/event`
- `devices/{device_id}/command`
- `devices/{device_id}/command_ack`
- `devices/{device_id}/log`

HTTP 和 WebSocket API：

- `GET /health`
- `GET /api/v1/devices`
- `GET /api/v1/devices/{device_id}/latest`
- `GET /api/v1/devices/{device_id}/capabilities`
- `POST /api/v1/devices/{device_id}/commands`
- `POST /api/v1/devices/{device_id}/ai/runs`
- `GET/PUT /api/v1/devices/{device_id}/automation-policy`
- `GET /api/v1/diagnostics/overview`
- `GET /api/v1/diagnostics/traces/{trace_id}`
- `POST /mcp`（Streamable HTTP，未配置 Token 时默认关闭）
- `WS /ws/devices/{device_id}`

完整的线路协议契约见 `docs/`。机器可读契约是 `server/openapi.json`（由 `server/scripts/export_openapi.py` 导出；CI 会对 drift 报错）。

## 本地开发

### 可视化面板（推荐）

不熟悉命令行时，双击项目根目录的 `启动配置面板.cmd`。面板只监听 `127.0.0.1:8765`，依次提供“环境中心、项目配置、服务控制、固件配置、固件操作、数据工具”。建议按以下顺序演示：

1. 在“环境中心”点“重新检查”。缺少基础软件时点“一键补全演示环境”；Docker 拉取失败时再测试网络、选择官方源/国内镜像或为 Docker Desktop 启用本机代理。
2. ESP-IDF 的检测与“安装/修复”也统一在“环境中心”。它优先读取 ESP-IDF Installation Manager（EIM）当前选中的安装实例，也支持自定义 `idf.eimIdfJsonPath` 和旧版安装布局；随后检查框架、Python 环境、CMake、Ninja、Xtensa ESP32-S3 工具链和 OpenOCD。支持能实际加载的 ESP-IDF `>=5.1,<6.0`。
3. 在“项目配置”分别选择设备来源和 AI 模式，保存配置。
4. 在“服务控制”启动 Docker 演示栈。若选择“固件模拟器”，面板会在 MQTT 和后端就绪后自动启动，并显示 MQTT、场景、Boot ID、遥测、执行器和最近命令状态。
5. 打开 Web 控制台 `http://localhost:3000`。后端健康检查为 `http://localhost:8000/health`，EMQX 控制台为 `http://localhost:18083`（默认 `admin / public`）。

“数据工具”可以预览或按分类清理某个设备在本地时间段内的数据，也可以用确定可重复的五阶段演示数据覆盖该时段的遥测和事件。该功能只通过监听回环地址的配置面板调用，不会新增公网 FastAPI 管理接口。

设备与 AI 是两个独立维度：

| 设备来源      | AI 模式      | 用途                                               |
| ------------- | ------------ | -------------------------------------------------- |
| 固件模拟器    | 本地 Mock AI | 推荐的离线软件演示；无需开发板、API Key 或外部模型 |
| 固件模拟器    | 在线大模型   | 用固件行为状态机验证真实模型判断                   |
| 真实 ESP32-S3 | 本地 Mock AI | 只验证硬件、MQTT 和执行闭环                        |
| 真实 ESP32-S3 | 在线大模型   | 完整真实演示                                       |

固件模拟器默认运行“正常环境”，也可切换“空气关注、空气告警、烟雾告警”。它从原始传感器值计算融合结果，执行与固件一致的本地安全和控制规则，并通过真实 MQTT/HTTP 上报能力、遥测、事件、图片及 `accepted`/终态 ACK。控制优先级和最近 16 个终态 ACK 写入模拟 NVS；重启后 Boot ID 和易失执行器状态会重置。面板可以重启固件或二次确认后清除模拟 NVS。

设备 ID、地址、采集间隔、工具调用上限等配置会在浏览器和工具端双重校验。每设备的巡检、定时视觉和久坐阈值属于运行时自动化策略，应在 Web 控制台配置，不再混入启动环境配置。

生成的根目录 `.env`、`server/.env` 和 `web/.env.local` 都是本机文件，已被 Git 忽略。不要提交 Wi-Fi 密码或 LLM API Key。

### 真实设备与固件

选择“真实 ESP32-S3”后，面板会生成适合局域网的 MQTT 和图片上传地址。“固件配置”写入本机 `sdkconfig`；“固件操作”只负责图形化配置、编译、烧录和监视。环境有问题应回到“环境中心”统一修复。

“使用模拟传感器数据”仍然运行在真实 ESP32-S3 固件内部，用来替代物理传感器读数；“固件模拟器”则是在电脑上运行的轻量固件行为状态机，不需要开发板，两者不是同一功能。

真实设备配置采用安全默认值，不会自动开启所有外设。面板会检查重复 GPIO、原生 USB 的 GPIO19/20 冲突，以及八线 PSRAM 的 GPIO35～37 冲突；未知板型仍标记为“待核对”。`configs/full-hardware.defaults` 仅用于编译覆盖，不能直接视为可烧录演示镜像。

### 命令行开发

Windows 手动开发命令使用 PowerShell 7。启动完整 AIoT 服务栈（TimescaleDB、EMQX、server、web）：

```powershell
docker compose up --build
```

如需手动运行固件模拟器（Docker 栈已就绪）：

```powershell
server\.venv\Scripts\python.exe tools\simulate-device.py --scenario air-alert --device-id esp32s3-001
```

默认每 2 秒发布遥测、每 30 秒上传图片，状态保存在 `.runtime/firmware-simulator/<device-id>/`。使用 `--no-image` 关闭图片，或通过 `--interval`、`--image-interval` 调整周期。

直接运行服务端（需要 Docker 里的 `postgres` + `emqx` 在跑）：

```powershell
cd server
uv sync
Copy-Item .env.example .env   # 直接运行时由它设置 AIOT_MQTT_ENABLED=true
uv run alembic upgrade head
uv run python run_dev.py
# 在第二个 PowerShell 窗口中，从 server\ 目录启动：
uv run python run_worker.py
```

启动网关与 Worker 前，先通过启动配置面板或 `tools/configure-local.ps1` 生成双方共享的内部 MCP Token。没有 `.env` 时 MQTT 接入默认关闭（`AIOT_MQTT_ENABLED=false`）。

直接运行 Web 控制台：

```powershell
cd web
pnpm install
pnpm dev
```

构建固件：

```powershell
cd firmware\esp32s3
idf.py -B build build
```

VS Code 的 `Tasks: Run Task` 仍可作为快捷入口；任务定义在 `.vscode/tasks.json`。固件环境检测/修复以可视化面板的“环境中心”为统一入口。

## 质量检查

```powershell
# 服务端
cd server
uv run ruff check . ; uv run ruff format --check . ; uv run mypy app ; uv run pytest

# 前端
cd web
pnpm lint ; pnpm format:check ; pnpm typecheck ; pnpm build

# 全仓
pre-commit run --all-files

# 修改服务端 schema/路由后重新生成 API 契约
python tools/generate-contracts.py
cd server ; uv run python scripts/export_openapi.py
cd ..\web ; pnpm codegen
```

GitHub Actions 按区域运行同样的检查（`server.yml` 含 OpenAPI drift 检查、`web.yml`、`firmware.yml`）。

本次软件验收包括后端 78 项测试、前端构建与 Playwright 闭环、双 Worker Docker 领取/AI-MCP-MQTT 链路、四种固件模拟场景，以及 ESP-IDF 5.5.2 默认/全功能隔离构建。由于没有真实开发板，USB/串口、实际 GPIO、供电、PSRAM、OV2640、显示、语音、传感器电平和机械动作仍未验证，不能用模拟器结果代替真机结论。

## 规则

- 将 `docs/` 和 `server/openapi.json` 视为协议契约。不要手工编辑 `web/src/lib/api-client/`——用 `pnpm codegen` 重新生成。
- 不要把 LLM API Key、Wi-Fi 密钥、MQTT 凭据和数据库密码写入源文件。
- MQTT 负责传感器遥测和命令。
- ESP32-S3 固件不得直接调用外部 LLM Provider；LLM 调用和命令校验由服务端负责。
- 不要提交构建输出、本地 `sdkconfig`、`managed_components/`、上传图像、数据库文件、虚拟环境、前端构建输出或本地 SDK checkout。已提交的生成物是例外：`server/openapi.json`、`web/src/lib/api-client/` 和 `firmware/esp32s3/dependencies.lock`（钉住 ESP-IDF 组件版本）是有意入库的。
