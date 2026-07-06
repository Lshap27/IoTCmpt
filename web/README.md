# AIoT Web Console

Next.js real-time control console for the new AIoT architecture.

The first screen is the working dashboard:

- device online state
- current sensor values
- latest image
- AI result and command state
- manual command controls
- telemetry history
- live event stream

The frontend reads initial state through HTTP and then listens for live updates
through `WS /ws/devices/{device_id}`.

## Local Run

```powershell
cd web
npm install
npm run dev
```

Set `NEXT_PUBLIC_API_BASE_URL` when the server is not on
`http://localhost:8000`.

