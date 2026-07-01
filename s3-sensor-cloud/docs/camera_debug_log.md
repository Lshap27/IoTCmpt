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