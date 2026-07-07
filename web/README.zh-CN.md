# AIoT Web 控制台

这是新 AIoT 架构的 Next.js 实时控制台。

首屏就是可工作的仪表盘：

- 设备在线状态
- 当前传感器数值
- 最新图像
- AI 结果和命令状态
- 手动命令控制
- 遥测历史
- 实时事件流

前端通过 HTTP 读取初始状态，然后通过 `WS /ws/devices/{device_id}` 监听实时更新。

## 本地运行

```powershell
cd web
pnpm install --ignore-scripts
pnpm run dev
```

当服务端不在 `http://localhost:8000` 时，设置 `NEXT_PUBLIC_API_BASE_URL`。

## 验证

```powershell
pnpm run build
```

在 Windows 上，如果 `node` 不在 `PATH` 中，请安装 Node.js LTS，或在 Node 和 pnpm 可用的 shell 中运行。
