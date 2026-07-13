# AIoT Web 控制台

这是 AIoT 架构的 Next.js 实时控制台。

技术栈：Next.js 15、React 19、TypeScript、Tailwind CSS v4（CSS-first `@theme`）、shadcn/ui、TanStack Query、Recharts、lucide-react。

首屏就是可工作的仪表盘（bento grid 布局）：

- 设备在线状态
- 当前传感器数值与迷你趋势线
- 实时遥测图表（原始与按时间分桶的历史）
- 最新图像
- AI 决策面板与按设备的自动决策开关
- 小时、日报、周报三种 AI 环境健康报告，包含数据完整度、异常、风险分和优先建议
- 手动命令控制
- 实时事件流
- 可持久化的宿舍通知与可选 SYN6288 语音状态

宿舍环境控制台继续使用 `/`；辅导员管理与通知页面位于 `/admin`。第一版将
`映雪3-301` 映射为演示设备 `esp32s3-001`，其余原型宿舍会明确标记为演示数据。

数据流：初始状态通过 HTTP 由 TanStack Query 拉取；之后 `WS /ws/devices/{device_id}` 的 WebSocket envelope 由 `src/lib/ws-dispatcher.ts`（基于 `WsMessage` 判别联合的纯函数）写入 query 缓存。Socket 断开后按指数退避自动重连（`src/hooks/use-device-socket.ts`）。

## API 客户端（生成物）

`src/lib/api-client/` 由 `@hey-api/openapi-ts` 从 `server/openapi.json` 生成。不要手工编辑：

```powershell
pnpm codegen
```

`src/lib/api.ts` 是生成 SDK 之上的手写薄包装。生成的客户端与服务端契约不一致时 CI 会失败。

## 本地运行

```powershell
cd web
pnpm install
pnpm dev
```

当服务端不在 `http://localhost:8000` 时，设置 `NEXT_PUBLIC_API_BASE_URL`。

## 验证

```powershell
pnpm lint
pnpm format:check
pnpm typecheck
pnpm build
```

在 Windows 上，如果 `node` 不在 `PATH` 中，请安装 Node.js LTS，或在 Node 和 pnpm 可用的 shell 中运行。
