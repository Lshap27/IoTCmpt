# OV2640 摄像头调试记录

## 2026-07-01

### 硬件
- 主控：ESP32-S3
- 摄像头：OV2640
- 接线：按队友提供的 OV2640 DVP 8-bit 接口表

### 软件
- ESP-IDF：v5.5.2
- 组件：espressif/esp32-camera
- 成功配置：
  - pixel_format = PIXFORMAT_JPEG
  - frame_size = FRAMESIZE_QQVGA
  - xclk_freq_hz = 10000000
  - fb_location = CAMERA_FB_IN_DRAM
  - fb_count = 1

### 结果
- 成功识别 OV2640，PID=0x26
- 成功连续采集 JPEG frame
- 日志显示 width=160, height=120, len≈2000 bytes

### 备注
- 20MHz XCLK 初次测试出现 SCCB_Write Failed
- 降到 10MHz 后成功

## QVGA 测试结果

### 配置
- pixel_format = PIXFORMAT_JPEG
- frame_size = FRAMESIZE_QVGA
- xclk_freq_hz = 10000000
- fb_location = CAMERA_FB_IN_DRAM
- fb_count = 1

### 结果
- 成功连续采集图像帧
- width = 320
- height = 240
- format = 4，即 JPEG
- frame len ≈ 4808 ~ 4816 bytes

### 结论
当前接线和软件配置下，OV2640 可稳定输出 QVGA JPEG 图像。

## 摄像头模块化测试

### 结果
- camera_pins.h 保存 OV2640 接线
- camera_app.c / camera_app.h 封装初始化与抓帧
- main.c 调用 camera_app_init() 和 camera_app_capture_once()
- 模块化后 QVGA JPEG 连续抓帧成功

### 日志
- width = 320
- height = 240
- frame len ≈ 4836 ~ 4880 bytes
- format = 4，即 JPEG

## 摄像头、WiFi共存测试

### 配置
- pixel_format = PIXFORMAT_JPEG
- frame_size = FRAMESIZE_QVGA
- xclk_freq_hz = 10000000
- fb_location = CAMERA_FB_IN_DRAM
- fb_count = 1
- Wi-Fi 模式：STA
- SSID：lnmot
- 加密：WPA2_PSK

### 结果
- Wi-Fi 成功连接，获取 IP 地址
- 摄像头初始化成功（OV2640, PID=0x26）
- Wi-Fi 连接保持稳定，未出现掉线
- 摄像头持续采集 JPEG 帧，未受 Wi-Fi 干扰
- 每 3 秒抓取一帧，循环运行稳定

### 日志
- Wi-Fi: Got IP: xxx.xxx.xxx.xxx
- width = 320
- height = 240
- format = 4，即 JPEG
- frame len ≈ 4800 ~ 5000 bytes

### 结论
当前接线和软件配置下，OV2640 摄像头与 Wi-Fi STA 可稳定共存。Wi-Fi 射频未对 DVP 并行接口造成明显干扰，JPEG 帧输出正常。模块化后的 camera_app 与 wifi_app 协同工作良好。

## HTTP 图像上传测试

### 时间
2026-07-01

### 硬件
- ESP32-S3
- OV2640 摄像头

### 软件配置
- ESP-IDF v5.5.2
- esp32-camera
- Wi-Fi STA 模式
- HTTP POST 上传
- Python HTTPServer 接收图片

### 摄像头参数
- pixel_format = PIXFORMAT_JPEG
- frame_size = FRAMESIZE_QVGA
- xclk_freq_hz = 10000000
- fb_location = CAMERA_FB_IN_DRAM
- fb_count = 1

### 结果
- ESP32-S3 成功连接 Wi-Fi
- OV2640 成功采集 QVGA JPEG
- ESP32-S3 成功 POST 到电脑服务端
- 服务端返回 HTTP 200
- 图片保存到电脑并可正常打开

### 关键日志
HTTP_UPLOAD: HTTP POST status=200, content_length=2
MAIN: Image upload success