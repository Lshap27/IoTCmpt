# IoTCmpt Web 控制台

这是 Next.js 15 + React 19 的实时操作界面。浏览器只访问 Gateway 的 HTTP `/api/v1` 和 WebSocket v2，不直接连接 MQTT、数据库或大模型。

## 页面

- `/`：设备环境、趋势、摄像头、手动命令、AI 任务、自动化策略、通知和事件流。
- `/admin`：保留的辅导员业务展示页；使用相同的新 API/Hook，不承载工程诊断。
- `/diagnostics`：非秘密工程诊断页，显示队列计数、Worker 心跳、MCP 开关、设备能力和 trace 时间线。

命令区展示 `queued -> published -> accepted -> terminal`，并显示来源、耗时、标准错误码和设备拒绝原因。AI 创建接口收到 `202` 后立即结束按钮等待，后续生命周期由 WebSocket 和查询缓存驱动。

## 数据流

初始状态由 TanStack Query 通过 HTTP 获取。`src/lib/ws-dispatcher.ts` 将 WebSocket 判别联合事件写入 Query Cache：

- 按每设备 `event_id` 有界去重；
- 重复遥测不追加第二个点；
- 终态命令不可被迟到的 `accepted` 或另一个终态覆盖；
- AI 事件同时更新任务详情和列表；
- 断线重连后重新读取快照、命令、能力、AI 列表和自动化策略。

## API 客户端

`src/lib/api-client/` 由 `@hey-api/openapi-ts` 根据 `server/openapi.json` 生成，不得手工修改：

```powershell
pnpm codegen
```

`src/lib/api.ts` 是生成 SDK 上的手写薄包装。

## 本地运行与检查

```powershell
cd web
pnpm install
pnpm dev

pnpm lint
pnpm format:check
pnpm typecheck
pnpm build
pnpm test:e2e
```

服务端不在 `http://localhost:8000` 时设置 `NEXT_PUBLIC_API_BASE_URL`。这是构建时公开地址，不能放秘密。Playwright 测试中的语音和烟雾场景会在对应模拟条件未启用时跳过。
