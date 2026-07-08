# IoTCmpt AIoT 工作区

这是一个面向比赛的 ESP32-S3 AIoT 工作区，系统按协议优先的方式组织：

```text
ESP32-S3 firmware -> MQTT/HTTP -> FastAPI AIoT Gateway -> TimescaleDB/WebSocket -> Next.js console
```

仓库只保留 AIoT 主线。MQTT 是遥测与控制的主干；HTTP 用于健康检查、仪表盘 API 和 JPEG 图像上传。HTTP/WebSocket 契约有单一事实来源：`server/openapi.json`，前端 API 客户端由它生成。

## 架构

- `firmware/esp32s3/`：面向 ESP32-S3-DevKitC-1 的 ESP-IDF（v5.5.2）固件。
- `server/`：FastAPI AIoT 网关——异步 MQTT 接入（aiomqtt）、HTTP API、WebSocket 扇出、TimescaleDB 持久化（Alembic 迁移）、图像存储、LLM 调用和命令校验。依赖用 uv 管理，Ruff 做 lint，mypy 做类型检查。
- `web/`：Next.js 15 + React 19 实时设备控制台——Tailwind CSS v4、shadcn/ui、TanStack Query，API 客户端由 OpenAPI 生成（`@hey-api/openapi-ts`）。
- `infra/`：部署说明和服务配置。
- `docs/`：架构、协议和数据模型契约。

## 协议入口

MQTT Topic：

- `devices/{device_id}/status`
- `devices/{device_id}/telemetry`
- `devices/{device_id}/event`
- `devices/{device_id}/command`
- `devices/{device_id}/command_ack`
- `devices/{device_id}/log`

HTTP 和 WebSocket API：

- `GET /health`
- `GET /api/devices`
- `GET /api/devices/{device_id}/latest`
- `GET /api/devices/{device_id}/history`
- `GET /api/devices/{device_id}/history/bucketed`
- `POST /api/devices/{device_id}/images`
- `POST /api/devices/{device_id}/ai/analyze`
- `POST /api/devices/{device_id}/commands`
- `GET/PUT /api/devices/{device_id}/autopilot`
- `WS /ws/devices/{device_id}`

完整的线路协议契约见 `docs/`。机器可读契约是 `server/openapi.json`（由 `server/scripts/export_openapi.py` 导出；CI 会对 drift 报错）。

## 本地开发

Windows 上使用 PowerShell 7。

推荐先用 VS Code 任务入口。打开本仓库后，按：

```text
Ctrl+Shift+P -> Tasks: Run Task
```

任务定义在 `.vscode/tasks.json`，配置生成脚本是 `tools/configure-local.ps1`。生成的 `.env`、`server/.env` 和 `web/.env.local` 都是本机配置，已被 `.gitignore` 忽略，不要提交真实密钥。

### VS Code 任务说明

`配置：本地离线演示（mock AI）`

用于最快跑通页面和 AI 决策流程，不需要真实 ESP32-S3、不需要 LLM API Key，也不需要外网模型服务。它会生成：

- 根目录 `.env`：给 `docker compose` 读取，例如让 Docker 栈使用 `AIOT_LLM_ENDPOINT=mock`。
- `server/.env`：给直接运行后端时读取。
- `web/.env.local`：让前端请求 `http://localhost:8000`。

例子：只想看看控制台界面、AI 面板、自动决策流程是否能跑，就先点这个任务，再点 `启动：完整 Docker 演示栈`。

`配置：真实设备演示`

用于把真实 ESP32-S3 接到电脑上的本地服务。脚本会提示填写设备 ID 和电脑局域网 IP，然后生成本机配置，并在终端里打印固件 `menuconfig` 应该填写的值，例如：

```text
APP_MQTT_BROKER_URI=mqtt://<电脑局域网IP>:1883
APP_IMAGE_UPLOAD_URL=http://<电脑局域网IP>:8000/api/devices/esp32s3-001/images
```

例子：电脑 IP 是 `192.168.1.23`，ESP32-S3 和电脑在同一个 Wi-Fi 下，就运行这个任务，把终端输出的 MQTT 和图片上传地址填到固件图形化配置里。

`配置：填写 LLM API`

用于把 mock AI 换成真实 OpenAI 兼容模型。脚本会提示填写 endpoint、model 和 API Key，API Key 输入时不会明文显示。常见 endpoint 示例见 `server/.env.example`。

例子：准备展示真实多模态分析时，先运行这个任务，填写模型配置；如果还要接真实设备，再运行 `配置：真实设备演示` 检查设备连接地址。

`启动：完整 Docker 演示栈`

用于一键启动完整本地系统：TimescaleDB/PostgreSQL、EMQX、FastAPI server 和 Next.js web。启动后访问：

- Web 控制台：`http://localhost:3000`
- 后端健康检查：`http://localhost:8000/health`
- EMQX 控制台：`http://localhost:18083`，默认账号 `admin / public`

例子：做演示时最推荐用这个任务，因为数据库、MQTT、后端和前端会一起启动，不需要分别开多个终端。

`停止：完整 Docker 演示栈`

用于停止上面的 Docker 服务。它只执行 `docker compose down`，不会删除数据库卷和上传文件卷；下次启动还能继续使用已有数据。

例子：演示结束后点这个任务，释放端口 `3000`、`8000`、`1883`、`5432`。

`启动：后端开发服务`

用于代码开发时单独启动 FastAPI 后端。它在 `server/` 目录执行 `uv run python run_dev.py`。使用这个任务前，一般需要 Docker 里的 PostgreSQL 和 EMQX 已经在运行，并且已经生成 `server/.env`。

例子：只改后端接口、MQTT 接入或 LLM 逻辑时，可以开数据库和 EMQX，再单独跑这个任务观察后端日志。

`启动：前端控制台`

用于代码开发时单独启动 Next.js 前端。它在 `web/` 目录执行 `pnpm dev`，默认访问 `http://localhost:3000`。使用这个任务前，后端应在 `http://localhost:8000`，或者通过 `web/.env.local` 改过 `NEXT_PUBLIC_API_BASE_URL`。

例子：只改仪表盘 UI、图表或交互时，运行这个任务即可，不需要重新构建完整 Docker 栈。

`固件：打开图形化配置`

用于打开 ESP-IDF 的 `menuconfig` 图形化配置界面。这里配置 ESP32-S3 端的设备 ID、Wi-Fi、MQTT Broker、图片上传 URL、摄像头/屏幕/执行器开关和硬件引脚。

例子：运行 `配置：真实设备演示` 后，把它打印出来的 MQTT 和图片上传地址复制到这个图形化配置界面里。

`固件：构建 ESP32-S3`

用于编译固件。它在 `firmware/esp32s3/` 执行：

```powershell
idf.py -B build-esp32s3 build
```

例子：改完 `menuconfig` 或固件代码后，先运行这个任务确认能编译，再烧录到开发板。

### 推荐使用流程

纯软件离线演示：

```text
配置：本地离线演示（mock AI）
启动：完整 Docker 演示栈
打开 http://localhost:3000
```

真实 ESP32-S3 演示：

```text
配置：真实设备演示
固件：打开图形化配置
固件：构建 ESP32-S3
启动：完整 Docker 演示栈
打开 http://localhost:3000
```

真实 LLM + 真实设备演示：

```text
配置：填写 LLM API
配置：真实设备演示
固件：打开图形化配置
固件：构建 ESP32-S3
启动：完整 Docker 演示栈
```

启动完整 AIoT 服务栈（TimescaleDB、EMQX、server、web）：

```powershell
docker compose up --build
```

直接运行服务端（需要 Docker 里的 `postgres` + `emqx` 在跑）：

```powershell
cd server
uv sync
Copy-Item .env.example .env   # 直接运行时由它设置 AIOT_MQTT_ENABLED=true
uv run alembic upgrade head
uv run python run_dev.py
```

注意：没有 `.env` 时 MQTT 接入默认关闭（`AIOT_MQTT_ENABLED=false`），网关会静默地在无 MQTT 状态下启动。

直接运行 Web 控制台：

```powershell
cd web
pnpm install
pnpm dev
```

构建固件：

```powershell
cd firmware\esp32s3
idf.py -B build-esp32s3 build
```

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
cd server ; uv run python scripts/export_openapi.py
cd ..\web ; pnpm codegen
```

GitHub Actions 按区域运行同样的检查（`server.yml` 含 OpenAPI drift 检查、`web.yml`、`firmware.yml`）。

## 规则

- 将 `docs/` 和 `server/openapi.json` 视为协议契约。不要手工编辑 `web/src/lib/api-client/`——用 `pnpm codegen` 重新生成。
- 不要把 LLM API Key、Wi-Fi 密钥、MQTT 凭据和数据库密码写入源文件。
- MQTT 负责传感器遥测和命令。
- ESP32-S3 固件不得直接调用外部 LLM Provider；LLM 调用和命令校验由服务端负责。
- 不要提交构建输出、本地 `sdkconfig`、`managed_components/`、上传图像、数据库文件、虚拟环境、前端构建输出或本地 SDK checkout。已提交的生成物是例外：`server/openapi.json`、`web/src/lib/api-client/` 和 `firmware/esp32s3/dependencies.lock`（钉住 ESP-IDF 组件版本）是有意入库的。
