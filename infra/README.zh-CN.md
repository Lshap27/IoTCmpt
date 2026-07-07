# AIoT 基础设施

根目录的 `docker-compose.yml` 是默认的本地部署入口。

服务：

- PostgreSQL：`localhost:5432`。
- EMQX MQTT Broker：`localhost:1883`。
- EMQX Dashboard：`http://localhost:18083`。
- FastAPI 网关：`http://localhost:8000`。
- Next.js 控制台：`http://localhost:3000`。

默认本地 EMQX Dashboard 凭据：

```text
admin / public
```

第一个演示服务栈启用了匿名 MQTT。进行任何非本地部署前，请添加 MQTT 凭据，并更新固件和服务端环境变量。

## 设备本地目标

ESP32-S3 和笔记本处于同一个 Wi-Fi 时：

- MQTT Broker：`<laptop-ip>:1883`
- 图像/API Base URL：`http://<laptop-ip>:8000`

## 密钥

不要在本仓库存放生产密钥。请用本地 `.env` 文件或部署专用的密钥存储保存：

- `AIOT_LLM_API_KEY`
- MQTT 用户名/密码
- Wi-Fi SSID/密码
- 本地演示用途以外的数据库密码
