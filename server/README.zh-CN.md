# AIoT 网关服务端

这是新 AIoT 架构的 FastAPI 网关。

职责：

- 订阅设备 MQTT Topic。
- 存储设备状态、遥测、事件、命令、AI 结果和图像资源。
- 将校验后的命令发布到 MQTT。
- 为 Web 控制台暴露 HTTP API。
- 通过 WebSocket 广播实时更新。
- 仅在服务端保存 LLM Provider 凭据。

## 本地运行

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

默认的直接运行配置会从环境变量读取 PostgreSQL 连接设置。测试会用 SQLite 覆盖数据库配置。

## 测试

```powershell
cd server
.\.venv\Scripts\python -m pytest tests
```

测试套件必须能在没有 PostgreSQL 或 EMQX 的情况下运行。它会使用 SQLite，并通过环境变量覆盖禁用 MQTT。

## 环境

将 `.env.example` 复制为 `.env`，用于本地直接运行配置。不要把真实 LLM Key 和 MQTT 凭据提交到源码控制。
