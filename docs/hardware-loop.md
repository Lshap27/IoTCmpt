# Hardware loop reproduction

The lightweight firmware behavior simulator exercises the production MQTT,
HTTP, database, WebSocket, and command-ack paths. It does not bypass the
gateway with browser-only mock data. Scenarios generate only bounded raw sensor
values; the shared firmware behavior contract drives fusion, local safety,
command queueing, terminal ACK replay, and control priority.

1. Start the stack with `AIOT_LLM_ENDPOINT=mock docker compose up --build`.
2. In another PowerShell 7 terminal, run:

   ```powershell
   server\.venv\Scripts\python.exe tools\simulate-device.py --scenario normal
   server\.venv\Scripts\python.exe tools\simulate-device.py --scenario air-watch
   server\.venv\Scripts\python.exe tools\simulate-device.py --scenario air-alert
   server\.venv\Scripts\python.exe tools\simulate-device.py --scenario smoke
   ```

3. Open `http://localhost:3000` and verify telemetry, periodic image upload, pose state,
   smoke events, LED/window/alarm commands, control-priority changes, manual
   lock release, command acknowledgements, and the report generated from
   persisted samples.

The one-pixel built-in JPEG verifies image transport and the no-person pose
path. It is uploaded every 30 seconds by default. Pass `--image <jpeg>` to
exercise a real person/posture image, `--no-image` to disable it, or use the
startup panel to change scenario and intervals. Simulated NVS lives under
`.runtime/firmware-simulator/<device-id>/` and is intentionally untracked.

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

## Current build evidence

With ESP-IDF 5.5.2, the safe default profile built to about `0xdf4a0` with 40%
of the application partition free. The isolated full compile profile built to
about `0x10d980` with 28% free. These figures are evidence for this revision,
not permanent limits; always use the newest build output.

## Real-board checklist

Do not flash an unknown board from the full compile profile. Before flashing:

1. Record the exact ESP32-S3 module, flash size, PSRAM type, USB wiring and board revision.
2. Draw the actual pin map and run the panel preflight. Resolve every duplicate GPIO, native-USB GPIO19/20 conflict and octal-PSRAM GPIO35-37 conflict.
3. Confirm 3.3 V/5 V requirements, common ground and separate actuator power where needed.
4. Keep the current OV2640 PWDN-only, `pin_xclk=-1` arrangement unless the physical schematic proves another clock source.
5. Put Wi-Fi, MQTT and image URLs only in local `sdkconfig`; use the laptop LAN address, not `localhost`.
6. Flash once with peripheral modules disabled, verify USB/serial boot and Wi-Fi, then enable modules in small groups.
7. Verify retained status/capabilities, telemetry, image upload, `accepted` and terminal ACK, duplicate `command_id`, command TTL and Wi-Fi/MQTT reconnect.
8. Test smoke handling with cloud services stopped. The local alarm and safety veto must still work.
9. Test manual priority before AI/MCP commands, and observe physical window/LED/alarm behavior rather than trusting the UI alone.
10. Hold smoke continuously and confirm local speech near 0, 30 and 60 seconds. Briefly clear MQ-2 for less than 1 second and confirm it does not create a new first announcement; clear for at least 1 second and confirm the next episode announces immediately.
11. While smoke remains active, issue `alarm.silence`. Confirm both buzzer and periodic speech pause, then resume after expiry. Confirm stable smoke clear cancels queued smoke retries.
12. Trigger ordinary air pollution while capturing serial and Gateway logs. Confirm firmware only publishes `recommend_open_window=true`, the Gateway system plan submits one `window.open`, and one Gateway speech command follows only a terminal `executed` ACK. Stop the Gateway and confirm ordinary ventilation no longer runs locally, while smoke alarm and the smoke close-window veto still do.
13. Run a `decision` speech goal and a sedentary-event run through Worker -> MCP `device_speak` -> outbox -> MQTT -> terminal ACK. A queued AI Run or a generated text decision alone is not a voice acceptance result.
14. Lighting combinations are software-covered but physical LED/camera acceptance is intentionally deferred. Before enabling it in the lab, verify dark/present, bright/absent, the two hold combinations, stale pose, unstable light, the global automation switch and manual-priority rejection.

This repository revision has no physical-board result. USB/serial, power,
real GPIO, PSRAM, OV2640 timing, display, voice, sensor voltage/logic levels and
mechanical actuator movement remain explicitly unverified.
