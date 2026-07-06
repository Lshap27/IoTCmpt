# AIoT Gateway Server

FastAPI gateway for the new AIoT architecture.

Responsibilities:

- Subscribe to device MQTT topics.
- Store device status, telemetry, events, commands, AI results, and image assets.
- Publish validated commands to MQTT.
- Expose HTTP APIs for the web console.
- Broadcast live updates through WebSocket.
- Keep LLM provider credentials on the server side only.

## Local Run

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The default direct-run configuration uses PostgreSQL connection settings from
environment variables. Tests override the database with SQLite.

