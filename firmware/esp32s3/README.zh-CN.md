# ESP32-S3 固件

该目录是 IoTCmpt 的 ESP-IDF 5.5.2 固件主线。固件负责感知、执行、本地实时规则和最终安全否决，不直接连接云端大模型。

## 运行行为

- MQTT 连接后发布 retained 在线状态和设备能力。
- 定期发布 MQTT v2 遥测、事件和日志。
- 将 JPEG 上传到 `POST /api/v1/devices/{device_id}/images`。
- 仅接受 MQTT v2 命令信封，校验版本、设备 ID、命令 ID、来源、参数、TTL、能力、优先级和安全联锁。
- 有效命令先回复 `accepted`，再由独立执行任务回复 `executed`、`rejected` 或 `failed`。
- 最近 16 个终态 ACK 按 `command_id` 写入 NVS；QoS 1 重发只重放结果，不重复驱动硬件。
- 接入 SNTP；系统时间可信时严格校验 `expires_at`，未同步时输出明确诊断。

## 硬件和本地规则

- SHT30、TVOC301 和 LM393 采样与空气融合。
- LM393 明暗输入可配置高/低有效极性。
- 自动优先模式在融合建议通风时本地开窗，空气恢复后不自动关窗。
- 烟雾规则和报警不等待服务器或 LLM；静音只暂时屏蔽烟雾报警源。
- OV2640 摄像头、ST7735 显示屏、SG90 舵机、有源蜂鸣器、SYN6288 和手动按钮按配置启用。
- 手动窗口目标进入执行器循环；人工优先和安全联锁可拒绝 AI/外部 MCP 命令。

能力按真实模块生成：窗口/报警、LED、显示和语音分别依赖自己的模块。参数、策略或安全拒绝返回 `rejected` 与标准错误码，只有运行故障返回 `failed`。

## 配置与预检

安全默认配置关闭 Wi-Fi、MQTT、图片、摄像头、显示、执行器、按钮和模拟传感器，可在无外设和无凭据时编译。通过 `idf.py menuconfig` 或本机 `sdkconfig` 启用实际功能；不得提交 `sdkconfig` 或其中的 Wi-Fi/MQTT 凭据和本机地址。

启动预检会阻止：

- 多个已启用功能使用同一 GPIO；
- 原生 USB 与 GPIO19/20 冲突；
- 八线 PSRAM 与 GPIO35～37 冲突。

未知板型仍需人工核对。当前 OV2640 保留 PWDN-only、`pin_xclk=-1` 的既有接线设计，没有硬件依据时不要增加 XCLK。

`configs/full-hardware.defaults` 只用于编译覆盖所有模块，Wi-Fi、MQTT 和图片上传仍关闭，不能直接当作上板演示镜像。

## 构建

```powershell
cd firmware\esp32s3
idf.py -B build build
```

本轮默认安全配置镜像约 `0xdf4a0`、应用分区余量约 40%；全功能编译检查镜像约 `0x10d980`、余量约 28%。具体数值会随代码和工具链变化，应以当前构建输出为准。

## 真机验收边界

编译和固件行为模拟器不能替代上板。本轮没有真实 ESP32-S3，尚未验证 USB/串口枚举、供电、实际 GPIO、PSRAM、OV2640 时序、显示、语音、传感器电平和执行器机械动作。使用真实设备前必须按 `docs/hardware-loop.md` 逐项检查。
