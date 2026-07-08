# AIoT Web Console

Next.js real-time control console for the AIoT architecture.

Stack: Next.js 15, React 19, TypeScript, Tailwind CSS v4 (CSS-first
`@theme`), shadcn/ui, TanStack Query, Recharts, lucide-react.

The first screen is the working dashboard (bento grid layout):

- device online state
- current sensor values with sparklines
- live telemetry chart (raw and time-bucketed history)
- latest image
- AI decision panel with per-device autopilot switch
- manual command controls
- live event stream

Data flow: initial state is fetched over HTTP with TanStack Query; after
that, WebSocket envelopes from `WS /ws/devices/{device_id}` are written into
the query cache by `src/lib/ws-dispatcher.ts` (a pure function over the
`WsMessage` discriminated union). The socket reconnects with exponential
backoff (`src/hooks/use-device-socket.ts`).

## API Client (generated)

`src/lib/api-client/` is generated from `server/openapi.json` by
`@hey-api/openapi-ts`. Never edit it by hand:

```powershell
pnpm codegen
```

`src/lib/api.ts` is the thin hand-written wrapper around the generated SDK.
CI fails when the generated client drifts from the server contract.

## Local Run

```powershell
cd web
pnpm install
pnpm dev
```

Set `NEXT_PUBLIC_API_BASE_URL` when the server is not on
`http://localhost:8000`.

## Verification

```powershell
pnpm lint
pnpm format:check
pnpm typecheck
pnpm build
```

On Windows, if `node` is not on `PATH`, install Node.js LTS or run through a
shell where Node and pnpm are available.
