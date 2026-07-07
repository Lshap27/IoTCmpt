# IoTCmpt AIoT 工作区

这是一个面向比赛的 ESP32-S3 AIoT 工作区，系统按协议优先的方式组织：

```text
ESP32-S3 firmware -> MQTT/HTTP -> FastAPI AIoT Gateway -> PostgreSQL/WebSocket -> Next.js console
```

当前仓库只保留新的 AIoT 主线。MQTT 是遥测与控制的主干；HTTP 用于健康检查、仪表盘 API 和 JPEG 图像上传。

## 架构

- `firmware/esp32s3/`：面向 ESP32-S3-DevKitC-1 的 ESP-IDF 固件。
- `server/`：FastAPI AIoT 网关，负责 MQTT 接入、HTTP API、WebSocket 扇出、PostgreSQL 持久化、图像存储、LLM 调用和命令校验。
- `web/`：Next.js 实时设备控制台。
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
- `POST /api/devices/{device_id}/images`
- `POST /api/devices/{device_id}/ai/analyze`
- `POST /api/devices/{device_id}/commands`
- `WS /ws/devices/{device_id}`

完整的线路协议契约见 `docs/`。

## 本地开发

Windows 上使用 PowerShell 7。

启动 AIoT 服务栈：

```powershell
docker compose up --build
```

直接运行服务端：

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

直接运行 Web 控制台：

```powershell
cd web
pnpm install --ignore-scripts
pnpm run dev
```

从仓库根目录构建固件：

```powershell
cd firmware\esp32s3
idf.py -B build-esp32s3 build
```

## 规则

- 将 `docs/` 视为协议契约。
- 不要把 LLM API Key、Wi-Fi 密钥、MQTT 凭据和数据库密码写入源文件。
- MQTT 负责传感器遥测和命令。
- ESP32-S3 固件不得直接调用外部 LLM Provider；LLM 调用和命令校验由服务端负责。
- 不要提交构建输出、本地 `sdkconfig`、`managed_components/`、`dependencies.lock`、上传图像、数据库文件、虚拟环境、前端构建输出或本地 SDK checkout。
