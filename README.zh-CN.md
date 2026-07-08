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
