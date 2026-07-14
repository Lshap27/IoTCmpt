# IoTCmpt 基础设施

根目录 `docker-compose.yml` 是本地演示和集成测试入口：

| 服务 | 作用 | 本机入口 |
| --- | --- | --- |
| postgres | PostgreSQL 16 + TimescaleDB，业务数据、租约、Outbox | `localhost:5432` |
| emqx | MQTT Broker | `localhost:1883` |
| emqx dashboard | Broker 管理页 | `http://localhost:18083` |
| server | 单进程 Gateway：HTTP/WS/MQTT/MCP | `http://localhost:8000` |
| worker | 可扩容 AI Worker 与巡检调度 | 无公网端口 |
| web | Next.js 控制台 | `http://localhost:3000` |

```powershell
docker compose up --build
docker compose ps
docker compose logs -f server worker
```

本地 EMQX Dashboard 默认账号为 `admin / public`，匿名 MQTT 仅用于受控本机演示。对局域网或公网开放前必须启用 Broker 身份验证、替换数据库密码、限制端口，并为外部 MCP 配置不同的只读/控制 Token 及 Host/Origin 白名单。

真实 ESP32-S3 与电脑同一 Wi-Fi 时，固件 MQTT 地址为 `<laptop-ip>:1883`，图片上传基址为 `http://<laptop-ip>:8000`。启动配置面板会生成局域网地址，但板型、PSRAM、USB 和 GPIO 仍须人工核对。

模型 Key 只注入 Worker；内部 MCP Token 只在 Gateway 与 Worker 之间共享；前端永远不应获得这两类秘密。`.env`、`server/.env`、`web/.env.local` 和固件 `sdkconfig` 都是本机文件，不进入 Git。
