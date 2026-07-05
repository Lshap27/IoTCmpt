# 宿智云 FastAPI 后端

这是当前仓库内的正式后端服务，替代队友原来的单文件 Demo。它保留 ESP32 固件已有上传接口，同时新增固件 `cloud_client` 可直接调用的云端 LLM 交换接口。

## 本地启动

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

也可以用 Docker Compose 启动 MySQL 和后端：

```bash
cd backend
docker compose up
```

## 固件 menuconfig URL

- `APP_SENSOR_UPLOAD_URL=http://<host>:8000/api/upload_sensor`
- `APP_IMAGE_UPLOAD_URL=http://<host>:8000/api/upload_image`
- `APP_POSE_UPLOAD_URL=http://<host>:8000/api/detect_pose`
- `APP_CLOUD_ENDPOINT=http://<host>:8000/api/cloud/exchange`

`APP_CLOUD_MODEL` 可以保留展示名；真实 LLM 模型由后端 `.env` 的 `APP_LLM_MODEL` 控制。若设置 `APP_DEVICE_TOKEN`，后端会校验 `/api/cloud/exchange` 的 Bearer token，固件侧 `APP_CLOUD_TOKEN` 需要填同一 token。

## 主要接口

- `POST /api/upload_sensor`：ESP32 上传传感器 JSON。
- `POST /api/upload_image`：ESP32 上传图片，仅存储。
- `POST /api/detect_pose`：ESP32 上传图片并触发 MediaPipe 姿态检测。
- `POST /api/cloud/exchange`：固件上传状态，后端调用 OpenAI-compatible LLM 并返回规范命令。
- `GET /api/latest`、`GET /api/history`、`GET /api/summary`：前端看板读取。
- `POST /api/command`、`GET /api/command/pending`、`POST /api/command/ack/{id}`：前端下发、设备轮询和确认。

## LLM 返回协议

后端会把 LLM 输出校验到固件当前支持的命令集合：

```json
{
  "command": "window.open",
  "confidence": 0.86,
  "parameter": "",
  "reason": "室内空气质量较差，建议开窗"
}
```

允许的命令是 `none`、`window.open`、`window.close`、`alarm.on`、`alarm.off`。LLM 未配置或返回非法命令时会降级为 `none`。

## 数据库

使用 Alembic 管理三张表：

- `sensor_readings`：传感器采样和本地融合状态。
- `pose_events`：图片、人体存在、姿态结果和标注图。
- `device_commands`：前端下发或云端生成的设备命令。

传感器采样和姿态事件分表存储，`/api/latest` 会聚合最新传感器记录和最新姿态记录，避免拍照刷新传感器采样时间。
