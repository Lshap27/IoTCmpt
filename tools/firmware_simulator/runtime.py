from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import aiomqtt

from .generated_behavior import COMMAND_EXECUTION_PERIOD_MS, COMMAND_QUEUE_LENGTH
from .model import FirmwareModel, iso_now
from .persistence import SimulatorStateStore
from .transport import EnvelopeEncoder, mqtt_client, upload_image

RECONNECT_DELAYS = (1, 2, 4, 8, 10)


class FirmwareSimulator:
    def __init__(self, args: Any):
        self.args = args
        self.store = SimulatorStateStore(
            Path(getattr(args, "state_dir", ".runtime/firmware-simulator")),
            args.device_id,
        )
        if getattr(args, "reset_state", False):
            self.store.clear_nvs()
        self.store.clear_stop_request()
        self.model = FirmwareModel(args.device_id, args.scenario, self.store.load_nvs())
        self.encoder = EnvelopeEncoder(args.device_id, self.model.boot_id)
        self.command_queue: asyncio.Queue[tuple[dict[str, Any], str]] = asyncio.Queue(
            maxsize=COMMAND_QUEUE_LENGTH
        )
        self.stop_event = asyncio.Event()
        self.mqtt_connected = False
        self.started_at = iso_now()
        self.last_telemetry_at: str | None = None
        self.last_image_at: str | None = None
        self.last_image_error: str | None = None
        self.last_error: str | None = None
        self._write_status()

    @property
    def state(self) -> dict[str, Any]:
        return self.model.state

    @property
    def boot_id(self) -> str:
        return self.model.boot_id

    @property
    def terminal_acks(self) -> dict[str, dict[str, Any]]:
        return self.model.terminal_acks

    def telemetry(self) -> dict[str, Any]:
        return self.model.telemetry()

    def capabilities(self) -> dict[str, Any]:
        return self.model.capabilities()

    def envelope(
        self, payload: dict[str, Any], *, trace_id: str | None = None
    ) -> dict[str, Any]:
        return self.encoder.encode(payload, trace_id=trace_id)

    def apply_command(self, payload: dict[str, Any]) -> tuple[str, str]:
        normalized = {"source": "frontend", "parameter": {}, **payload}
        if normalized.get("type") == "alarm.silence":
            parameter = dict(normalized.get("parameter") or {})
            if "seconds" in parameter and "duration_seconds" not in parameter:
                parameter["duration_seconds"] = parameter.pop("seconds")
            normalized["parameter"] = parameter
        status, message, _ = self.model.apply_command(normalized)
        return status, message

    async def run(self) -> None:
        self._install_signal_handlers()
        image_enabled = not getattr(self.args, "no_image", False)
        mqtt_task = asyncio.create_task(self._mqtt_supervisor(), name="mqtt-supervisor")
        tasks = [
            mqtt_task,
            asyncio.create_task(self._stop_file_monitor(), name="stop-file-monitor"),
            asyncio.create_task(self._status_loop(), name="status-heartbeat"),
        ]
        if image_enabled:
            tasks.append(asyncio.create_task(self._image_loop(), name="image-loop"))
        try:
            await self.stop_event.wait()
        finally:
            try:
                await asyncio.wait_for(asyncio.shield(mqtt_task), timeout=2)
            except (TimeoutError, asyncio.CancelledError):
                pass
            except Exception as exc:
                self.last_error = f"MQTT shutdown failed: {exc}"
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.mqtt_connected = False
            self._write_status(running=False)
            self.store.clear_stop_request()

    async def _mqtt_supervisor(self) -> None:
        retry = 0
        while not self.stop_event.is_set():
            offline = self.encoder.encode({"status": "offline"})
            try:
                async with mqtt_client(
                    self.args.host,
                    self.args.port,
                    self.args.device_id,
                    offline,
                ) as client:
                    retry = 0
                    self.mqtt_connected = True
                    self.last_error = None
                    self._write_status()
                    await self._run_connection(client)
            except asyncio.CancelledError:
                raise
            except (aiomqtt.MqttError, OSError) as exc:
                self.last_error = f"MQTT disconnected: {exc}"
            finally:
                self.mqtt_connected = False
                self._write_status()
            if self.stop_event.is_set():
                return
            delay = RECONNECT_DELAYS[min(retry, len(RECONNECT_DELAYS) - 1)]
            retry += 1
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def _run_connection(self, client: aiomqtt.Client) -> None:
        prefix = f"devices/{self.args.device_id}"
        await client.publish(
            f"{prefix}/status",
            json.dumps(self.encoder.encode({"status": "online"}), ensure_ascii=False),
            qos=1,
            retain=True,
        )
        await client.publish(
            f"{prefix}/capabilities",
            json.dumps(
                self.encoder.encode(self.model.capabilities()), ensure_ascii=False
            ),
            qos=1,
            retain=True,
        )
        await client.subscribe(f"{prefix}/command", qos=1)
        tasks = [
            asyncio.create_task(self._telemetry_loop(client), name="telemetry"),
            asyncio.create_task(
                self._command_receive_loop(client), name="command-receive"
            ),
            asyncio.create_task(
                self._command_execute_loop(client), name="command-execute"
            ),
            asyncio.create_task(self.stop_event.wait(), name="connection-stop"),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            if task.cancelled():
                continue
            error = task.exception()
            if error:
                raise error
        if self.stop_event.is_set():
            try:
                await client.publish(
                    f"{prefix}/status",
                    json.dumps(
                        self.encoder.encode({"status": "offline"}), ensure_ascii=False
                    ),
                    qos=1,
                    retain=True,
                )
            except aiomqtt.MqttError:
                pass

    async def _telemetry_loop(self, client: aiomqtt.Client) -> None:
        prefix = f"devices/{self.args.device_id}"
        previous_smoke = False
        while True:
            payload = self.model.telemetry()
            smoke = bool(payload["sensors"]["smoke_detected"])
            if smoke != previous_smoke:
                await client.publish(
                    f"{prefix}/event",
                    json.dumps(
                        self.encoder.encode(
                            {
                                "type": "smoke.detected" if smoke else "smoke.cleared",
                                "severity": "critical" if smoke else "info",
                                "message": "固件模拟器检测到烟雾"
                                if smoke
                                else "固件模拟器烟雾状态已清除",
                            }
                        ),
                        ensure_ascii=False,
                    ),
                    qos=1,
                )
            previous_smoke = smoke
            await client.publish(
                f"{prefix}/telemetry",
                json.dumps(self.encoder.encode(payload), ensure_ascii=False),
                qos=0,
            )
            self.last_telemetry_at = payload["sampled_at"]
            self._write_status()
            await asyncio.sleep(self.args.interval)

    async def _command_receive_loop(self, client: aiomqtt.Client) -> None:
        async for message in client.messages:
            try:
                envelope = json.loads(bytes(message.payload))
            except (ValueError, UnicodeDecodeError, TypeError):
                continue
            if not isinstance(envelope, dict):
                continue
            payload = envelope.get("payload")
            if not isinstance(payload, dict):
                payload = {}
            trace_id = str(envelope.get("trace_id") or uuid.uuid4())
            command_id = str(payload.get("command_id") or "")
            validation = self.model.validate_command(envelope, payload)
            if validation:
                error_code, message_text = validation
                await self._publish_terminal(
                    client,
                    command_id,
                    trace_id,
                    "rejected",
                    message_text,
                    error_code,
                    remember=bool(command_id),
                )
                continue
            cached = self.model.terminal_acks.get(command_id)
            if cached:
                await self._publish_ack(client, cached, trace_id)
                continue
            if self.command_queue.full():
                await self._publish_terminal(
                    client,
                    command_id,
                    trace_id,
                    "rejected",
                    "command queue is full",
                    "device_rejected",
                )
                continue
            await self.command_queue.put((payload, trace_id))
            await self._publish_ack(
                client,
                self._ack(command_id, "accepted", "queued", None),
                trace_id,
            )

    async def _command_execute_loop(self, client: aiomqtt.Client) -> None:
        while True:
            payload, trace_id = await self.command_queue.get()
            try:
                await asyncio.sleep(COMMAND_EXECUTION_PERIOD_MS / 1000)
                if getattr(self.args, "ack_delay", 0):
                    await asyncio.sleep(self.args.ack_delay)
                status, message, error_code = self.model.apply_command(payload)
                await self._publish_terminal(
                    client,
                    str(payload["command_id"]),
                    trace_id,
                    status,
                    message,
                    error_code,
                )
            finally:
                self.command_queue.task_done()

    async def _publish_terminal(
        self,
        client: aiomqtt.Client,
        command_id: str,
        trace_id: str,
        status: str,
        message: str,
        error_code: str | None,
        *,
        remember: bool = True,
    ) -> None:
        ack = self._ack(command_id, status, message, error_code)
        if remember:
            self.model.remember_terminal_ack(ack)
            self.store.save_nvs(self.model.nvs_snapshot())
            self._write_status()
        await self._publish_ack(client, ack, trace_id)

    async def _publish_ack(
        self, client: aiomqtt.Client, ack: dict[str, Any], trace_id: str
    ) -> None:
        await client.publish(
            f"devices/{self.args.device_id}/command_ack",
            json.dumps(self.encoder.encode(ack, trace_id=trace_id), ensure_ascii=False),
            qos=1,
        )

    def _ack(
        self, command_id: str, status: str, message: str, error_code: str | None
    ) -> dict[str, Any]:
        return {
            "command_id": command_id,
            "status": status,
            "message": message,
            "error_code": error_code,
            "executed_at": iso_now(),
            "reported_state": dict(self.model.state),
        }

    async def _image_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await upload_image(
                    self.args.api_base,
                    self.args.device_id,
                    getattr(self.args, "image", None),
                )
                self.model.image_count += 1
                self.last_image_at = iso_now()
                self.last_image_error = None
            except Exception as exc:  # Image upload is deliberately fail-soft.
                self.last_image_error = str(exc)
            self._write_status()
            try:
                await asyncio.wait_for(
                    self.stop_event.wait(), timeout=self.args.image_interval
                )
            except TimeoutError:
                pass

    async def _stop_file_monitor(self) -> None:
        while not self.stop_event.is_set():
            if self.store.stop_requested():
                self.stop_event.set()
                return
            await asyncio.sleep(0.25)

    async def _status_loop(self) -> None:
        while not self.stop_event.is_set():
            self._write_status()
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=2)
            except TimeoutError:
                pass

    def _write_status(self, *, running: bool = True) -> None:
        telemetry = self.model.last_telemetry
        status = {
            "schema_version": 1,
            "updated_at": iso_now(),
            "running": running,
            "mqtt_connected": self.mqtt_connected,
            "scenario": self.model.scenario,
            "device_id": self.args.device_id,
            "boot_id": self.model.boot_id,
            "started_at": self.started_at,
            "last_telemetry_at": self.last_telemetry_at,
            "last_image_at": self.last_image_at,
            "last_image_error": self.last_image_error,
            "telemetry_count": self.model.telemetry_count,
            "image_count": self.model.image_count,
            "command_count": self.model.command_count,
            "state": dict(self.model.state),
            "last_command": self.model.last_command,
            "last_voice_content": self.model.last_voice_content,
            "last_display_content": self.model.last_display_content,
            "last_telemetry": telemetry,
            "last_error": self.last_error,
            "pid": __import__("os").getpid(),
        }
        self.store.write_status(status)

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for signal_name in ("SIGINT", "SIGTERM"):
            signal_value = getattr(__import__("signal"), signal_name, None)
            if signal_value is None:
                continue
            try:
                loop.add_signal_handler(signal_value, self.stop_event.set)
            except (NotImplementedError, RuntimeError):
                pass
