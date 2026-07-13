# ESP32-S3 固件

该目录是 AIoT 架构的 ESP-IDF 固件主线。

## 行为

- 通过 MQTT 发布 retained online/offline 状态。
- 定期向 `devices/{device_id}/telemetry` 发布遥测数据。
- 将 JPEG 图像上传到 `POST /api/devices/{device_id}/images`。
- 订阅 `devices/{device_id}/command`。
- 在本地执行受支持的命令。
- 执行后发布 `devices/{device_id}/command_ack`。

## 硬件模块

- SHT30、TVOC301 和 LM393 采样。
- 本地融合规则。
- OV2640 摄像头。
- ST7735 显示屏。
- SG90 舵机。
- 有源蜂鸣器。
- 手动按钮。
- 运行时控制状态。

## 配置

默认配置会禁用 Wi-Fi、MQTT、图像上传、摄像头、显示屏、执行器和按钮模块，使项目在没有本地凭据或外接硬件的情况下也能编译。

通过 `idf.py menuconfig` 或本地 `sdkconfig` 启用运行时功能。
不要提交 Wi-Fi 凭据、MQTT 凭据、LLM Key 或本地服务器地址。

## 构建

从仓库根目录使用 PowerShell 7：

```powershell
cd firmware\esp32s3
idf.py -B build build
```

## MQTT 行为

启用 Wi-Fi 和 MQTT 后，固件会：

- 连接到已配置的 Broker URI；
- 发布 retained `online` 状态；
- 从真实或模拟传感器定期发布遥测数据；
- 订阅 `devices/{device_id}/command`；
- 执行 `window.open`、`window.close`、`alarm.on` 和 `alarm.off`；
- 发布状态为 `executed`、`rejected` 或 `failed` 的命令 ACK。
