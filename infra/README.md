# IoTCmpt Infrastructure

Root `docker-compose.yml` is the local demo and integration-test entry point:

| Service | Purpose | Host entry point |
| --- | --- | --- |
| postgres | PostgreSQL 16 + TimescaleDB for data, leases, and outboxes | `localhost:5432` |
| emqx | MQTT broker | `localhost:1883` |
| EMQX dashboard | Broker administration | `http://localhost:18083` |
| server | Single-process HTTP/WS/MQTT/MCP Gateway | `http://localhost:8000` |
| worker | Scalable AI Worker and patrol scheduler | no public port |
| web | Next.js console | `http://localhost:3000` |

```powershell
docker compose up --build
docker compose ps
docker compose logs -f server worker
```

The local EMQX dashboard uses `admin / public`; anonymous MQTT is for a controlled local demo only. Before exposing the stack, enable broker authentication, replace database passwords, restrict ports, and configure distinct external MCP read/control tokens plus valid Host/Origin allowlists.

For a board on the same Wi-Fi, use `<laptop-ip>:1883` for MQTT and `http://<laptop-ip>:8000` as the image API base. The setup panel can generate LAN targets, but board type, PSRAM, USB, and GPIO wiring still require manual verification.

Provider keys belong only to the Worker. The internal MCP token is shared only by Gateway and Worker. Local `.env`, `server/.env`, `web/.env.local`, and firmware `sdkconfig` files are untracked and must remain secret.
