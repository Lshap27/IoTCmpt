# IoTCmpt 服务端

`server/` 同时包含两个可独立启动的进程：

- **Gateway**：FastAPI、HTTP/WebSocket、MQTT 接入、MCP Server、Outbox 发布和实时事件转发。
- **AI Worker**：云端模型调用、MCP Host、报告、事件分析、周期巡检和任务恢复。

两者共享 PostgreSQL/TimescaleDB，但只有 Worker 加载 LLM Provider、API Key 和模型参数。模型故障不会阻塞遥测、人工命令或固件本地安全规则。

## 代码边界

- `app/domain/`：设备、命令、AI 任务和策略规则，不依赖框架。
- `app/application/`：查询、命令、报告和诊断用例。
- `app/ports/`：数据库、MQTT、LLM、MCP、时钟和 ID 接口。
- `app/adapters/`：SQLAlchemy、MQTT、MCP、模型、Outbox、Realtime Relay 实现。
- `app/api/`：FastAPI 传输适配器。
- `app/main.py`：Gateway 依赖组合。
- `app/worker_main.py`：Worker 依赖组合。

HTTP、MQTT 和 MCP 都进入同一套应用用例，不允许各自绕过业务校验直接发布 MQTT。`tests/test_architecture.py` 检查分层导入方向。

## 可靠任务模型

AI Run、MQTT Outbox 和 Realtime Event 都使用 PostgreSQL 行租约。每次领取都会生成唯一 `lease_token`，续租、完成、失败和重试必须同时匹配 `id + lease_owner + lease_token`。旧 Worker 即使在网络停顿后恢复，也不能继续提交副作用。

AI 控制工具的幂等键由 `run_id + round + call_index` 稳定派生；Worker 重试不会生成第二条硬件命令。取消和租约状态会在模型调用、MCP 调用及最终提交前复核。

## 本地运行

先启动根目录 Docker 中的 `postgres` 和 `emqx`，再使用两个 PowerShell 7 窗口：

```powershell
cd server
uv sync
Copy-Item .env.example .env
uv run alembic upgrade head
uv run python run_dev.py
```

```powershell
cd server
uv run python run_worker.py
```

Gateway 固定单进程；Worker 可以扩容。Docker Compose 默认同时启动 Gateway 和一个 Worker。启动配置面板会生成两者共享、不会暴露给浏览器的 `AIOT_MCP_INTERNAL_TOKEN`。

## 接口与诊断

- 业务接口全部位于 `/api/v1`。
- MCP 使用 `/mcp` Streamable HTTP；外部访问默认关闭，读写 Token 必须不同。
- WebSocket v2 位于 `/ws/devices/{device_id}`。
- `/health/ready` 返回数据库、MQTT、Worker、MCP 和迁移状态；Worker 故障是 degraded，不阻断人工控制。
- `/api/v1/diagnostics/overview` 返回非秘密队列、Worker 心跳、MCP 开关和设备能力。
- `/api/v1/diagnostics/traces/{trace_id}` 返回统一时间线。

## 迁移

数据库结构只通过 `alembic/versions/` 演进。`0006` 引入架构 v2，`0007` 完成可靠 Worker 切换和旧 AI 历史迁移，`0008` 增加租约 fencing 与 MQTT 入站幂等。不要修改已经可能被应用的迁移。

```powershell
uv run alembic upgrade head
```

## 检查与生成

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
uv run python scripts/export_openapi.py
cd ..\web
pnpm codegen
```

测试默认使用 SQLite，不要求 PostgreSQL 或 EMQX；双 Worker、租约恢复和完整 MQTT 闭环使用 Docker 集成环境。真实 `.env`、模型 Key、MCP Token 和 MQTT 凭据不得提交。
