# AIoT 网关服务端

这是 AIoT 架构的 FastAPI 网关。

职责：

- 订阅设备 MQTT Topic（aiomqtt，单 asyncio 事件循环，自动重连）。
- 将设备状态、遥测、事件、命令、AI 结果和图像资源存入 TimescaleDB/PostgreSQL（遥测为 hypertable）。
- 将校验后的命令发布到 MQTT。
- 为 Web 控制台暴露 HTTP API；所有 endpoint 都声明 `response_model`，`openapi.json` 是入库的 API 契约。
- 通过 WebSocket 广播实时更新（`WsMessage` 判别联合）。
- 仅在服务端保存 LLM Provider 凭据。

工程工具：依赖用 uv 管理（`pyproject.toml` + `uv.lock`），Ruff 做 lint/格式化，mypy 做类型检查，Alembic 做迁移。

## 本地运行

需要仓库根目录 Docker 里的 `postgres` 和 `emqx` 服务。

```powershell
cd server
uv sync
Copy-Item .env.example .env   # 直接运行时由它启用 AIOT_MQTT_ENABLED=true
uv run alembic upgrade head
uv run python run_dev.py
```

`run_dev.py` 以 aiomqtt 需要的 Windows `SelectorEventLoop` 策略启动 uvicorn。没有 `.env` 时 `AIOT_MQTT_ENABLED` 默认 `false`，网关会在无 MQTT 接入的状态下启动（不会报错）。

## 测试与检查

```powershell
cd server
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```

测试套件必须能在没有 PostgreSQL 或 EMQX 的情况下运行。它使用 SQLite，并通过 `tests/conftest.py` 里的环境变量覆盖禁用 MQTT。

## API 契约

修改 schema 或路由后，重新导出 OpenAPI 文档并重新生成前端客户端：

```powershell
uv run python scripts/export_openapi.py
cd ..\web
pnpm codegen
```

当 `openapi.json` 或生成的客户端与代码不一致时，CI（`.github/workflows/server.yml`）会失败。

## 迁移

Schema 变更走 Alembic（`alembic/versions/`）。`0001` 创建初始 schema；`0002` 把 `telemetry` 转为 TimescaleDB hypertable。用 `uv run alembic upgrade head` 应用。Docker 镜像启动时会执行 `alembic upgrade head`；由迁移管理 schema 时 `AIOT_AUTO_CREATE_TABLES` 保持 `false`。

## 环境

将 `.env.example` 复制为 `.env`，用于本地直接运行配置。不要把真实 LLM Key 和 MQTT 凭据提交到源码控制。
