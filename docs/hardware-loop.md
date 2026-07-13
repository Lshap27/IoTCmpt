# Hardware loop reproduction

The simulator exercises the production MQTT, HTTP, database, WebSocket, and
command-ack paths. It does not bypass the gateway with browser-only mock data.
Every scenario produces bounded, deterministic fluctuations for temperature,
humidity, TVOC, formaldehyde, and eCO2 instead of publishing frozen values.

1. Start the stack with `AIOT_LLM_ENDPOINT=mock docker compose up --build`.
2. In another PowerShell 7 terminal, run:

   ```powershell
   server\.venv\Scripts\python.exe tools\simulate-device.py --scenario normal
   server\.venv\Scripts\python.exe tools\simulate-device.py --scenario air-alert
   server\.venv\Scripts\python.exe tools\simulate-device.py --scenario smoke
   ```

3. Open `http://localhost:3000` and verify telemetry, image upload, pose state,
   smoke events, LED/window/alarm commands, control-priority changes, manual
   lock release, command acknowledgements, and the report generated from
   persisted samples.

The one-pixel built-in JPEG verifies image transport and the no-person pose
path. Pass `--image <jpeg>` to exercise a real person/posture image.

Firmware compile-only full feature profile:

```powershell
cd firmware\esp32s3
$fullBuild = Join-Path ([System.IO.Path]::GetTempPath()) "iotcmpt-esp32s3-full"
try {
  idf.py -B $fullBuild `
    -D "SDKCONFIG=$fullBuild\sdkconfig" `
    -D SDKCONFIG_DEFAULTS=configs/full-hardware.defaults build
  if ($LASTEXITCODE -ne 0) { throw "Full-feature firmware build failed." }
} finally {
  Remove-Item -LiteralPath $fullBuild -Recurse -Force -ErrorAction SilentlyContinue
}
```

This validates code generation and linking for MQ-2, SYN6288, GPIO LED,
camera, display, actuator, and button modules. Physical behavior still requires
the actual board and wiring. Its isolated build files live under the system
temporary directory and are removed afterward, so the repository keeps only
the normal `firmware/esp32s3/build` directory. The compatibility profile drives
the LED on GPIO41; the normal default remains logical-only until GPIO mode is
explicitly enabled.
