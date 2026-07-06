# AIoT Infrastructure

Root `docker-compose.yml` is the default local deployment entrypoint.

Services:

- PostgreSQL on `localhost:5432`.
- EMQX MQTT broker on `localhost:1883`.
- EMQX dashboard on `http://localhost:18083`.
- FastAPI gateway on `http://localhost:8000`.
- Next.js console on `http://localhost:3000`.

Default local EMQX dashboard credentials:

```text
admin / public
```

Anonymous MQTT is enabled for the first demo stack. Before any non-local
deployment, add MQTT credentials and update firmware/server environment values.

## Device Local Targets

When the ESP32-S3 and laptop are on the same Wi-Fi:

- MQTT broker: `<laptop-ip>:1883`
- Image/API base URL: `http://<laptop-ip>:8000`

## Simulated Device

After the Compose stack is running, publish test telemetry from the repository
root:

```powershell
server\.venv\Scripts\python.exe scripts\simulate-device.py --host 127.0.0.1 --device-id esp32s3-001
```

Expected checks:

- `GET http://localhost:8000/api/devices/esp32s3-001/latest` shows telemetry.
- `http://localhost:3000` updates the dashboard.
- Manual commands from the dashboard are printed by the simulator and
  acknowledged through `devices/esp32s3-001/command_ack`.

## Secrets

Do not store production secrets in this repository. Use local `.env` files or
deployment-specific secret stores for:

- `AIOT_LLM_API_KEY`
- MQTT username/password
- Wi-Fi SSID/password
- database passwords outside local demo use
