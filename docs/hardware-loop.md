# Hardware loop reproduction

The simulator exercises the production MQTT, HTTP, database, WebSocket, and
command-ack paths. It does not bypass the gateway with browser-only mock data.

1. Start the stack with `AIOT_LLM_ENDPOINT=mock docker compose up --build`.
2. In another PowerShell 7 terminal, run:

   ```powershell
   server\.venv\Scripts\python.exe tools\simulate-device.py --scenario normal
   server\.venv\Scripts\python.exe tools\simulate-device.py --scenario air-alert
   server\.venv\Scripts\python.exe tools\simulate-device.py --scenario smoke
   ```

3. Open `http://localhost:3000` and verify telemetry, image upload, pose state,
   smoke events, LED/window/alarm commands, command acknowledgements, and the
   report generated from persisted samples.

The one-pixel built-in JPEG verifies image transport and the no-person pose
path. Pass `--image <jpeg>` to exercise a real person/posture image.

Firmware compile-only full feature profile:

```powershell
cd firmware\esp32s3
idf.py -B build-ci-full `
  -D SDKCONFIG=build-ci-full/sdkconfig `
  -D SDKCONFIG_DEFAULTS=configs/full-hardware.defaults build
```

This validates code generation and linking for MQ-2, SYN6288, GPIO LED,
camera, display, actuator, and button modules. Physical behavior still requires
the actual board and wiring. The compatibility profile drives the LED on GPIO41;
the normal default remains logical-only until GPIO mode is explicitly enabled.
