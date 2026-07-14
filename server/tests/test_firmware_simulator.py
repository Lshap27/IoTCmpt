from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.firmware_simulator.generated_behavior import COMMAND_QUEUE_LENGTH, TERMINAL_ACK_CACHE_SIZE  # noqa: E402
from tools.firmware_simulator.model import FirmwareModel, ScenarioSensor, fuse_sample  # noqa: E402
from tools.firmware_simulator.persistence import SimulatorStateStore  # noqa: E402
from tools.firmware_simulator.runtime import FirmwareSimulator  # noqa: E402


def make_args(tmp_path: Path, **overrides):
    values = {
        "scenario": "normal",
        "device_id": "esp32s3-test",
        "host": "127.0.0.1",
        "port": 1883,
        "api_base": "http://127.0.0.1:8000",
        "interval": 2.0,
        "ack_delay": 0.0,
        "image": None,
        "image_interval": 30.0,
        "no_image": True,
        "state_dir": str(tmp_path),
        "reset_state": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def command_envelope(command_id: str, command_type: str, **payload_overrides):
    payload = {
        "command_id": command_id,
        "type": command_type,
        "source": "frontend",
        "parameter": {},
        **payload_overrides,
    }
    return {
        "schema_version": "2.0",
        "message_id": f"message-{command_id}",
        "device_id": "esp32s3-test",
        "trace_id": f"trace-{command_id}",
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "boot_id": "gateway-test",
        "sequence": 1,
        "payload": payload,
    }


class FakeMessage:
    def __init__(self, body):
        self.payload = json.dumps(body).encode()


class FakeMessages:
    def __init__(self, messages):
        self.messages = messages

    def __aiter__(self):
        self.iterator = iter(self.messages)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeClient:
    def __init__(self, messages=()):
        self.messages = FakeMessages([FakeMessage(item) for item in messages])
        self.published = []

    async def publish(self, topic, payload, **options):
        self.published.append((topic, json.loads(payload), options))

    async def subscribe(self, *_args, **_kwargs):
        return None


def test_scenarios_generate_raw_values_and_fusion_matches_firmware_thresholds():
    expected = {
        "normal": ("good", False, False),
        "air-watch": ("watch", True, False),
        "air-alert": ("alert", True, False),
        "smoke": ("alert", False, True),
    }
    for scenario, result in expected.items():
        sensor = ScenarioSensor(scenario)
        samples = [sensor.sample() for _ in range(5)]
        assert all(
            (
                fuse_sample(sample)["air_quality"],
                fuse_sample(sample)["recommend_open_window"],
                fuse_sample(sample)["alarm_enabled"],
            )
            == result
            for sample in samples
        )
        assert len({sample["temperature_c"] for sample in samples}) > 1


def test_auto_first_opens_window_but_recovery_does_not_close_it():
    model = FirmwareModel("esp32s3-test", "air-alert", {"control_priority": "auto_first"})
    assert model.telemetry()["state"]["window_open"] is True
    model.scenario = "normal"
    model.sensor = ScenarioSensor("normal")
    assert model.telemetry()["state"]["window_open"] is True


def test_command_validation_checks_source_parameters_and_ttl():
    model = FirmwareModel("esp32s3-test")
    envelope = command_envelope("c1", "alarm.off", source="ai")
    assert model.validate_command(envelope, envelope["payload"])[0] == "policy_denied"

    envelope = command_envelope("c2", "alarm.silence", parameter={"duration_seconds": 9})
    assert model.validate_command(envelope, envelope["payload"])[0] == "invalid_parameter"

    envelope = command_envelope(
        "c3",
        "window.open",
        expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    )
    assert model.validate_command(envelope, envelope["payload"])[0] == "expired"


def test_command_ack_is_accepted_before_terminal_and_duplicate_replays(tmp_path):
    async def exercise():
        simulator = FirmwareSimulator(make_args(tmp_path))
        envelope = command_envelope("c1", "window.open")
        client = FakeClient([envelope])
        await simulator._command_receive_loop(client)
        executor = asyncio.create_task(simulator._command_execute_loop())
        ack_publisher = asyncio.create_task(simulator._ack_publish_loop(client))
        await asyncio.wait_for(simulator.command_queue.join(), timeout=2)
        await asyncio.wait_for(simulator.ack_queue.join(), timeout=2)
        executor.cancel()
        ack_publisher.cancel()
        await asyncio.gather(executor, ack_publisher, return_exceptions=True)

        statuses = [item[1]["payload"]["status"] for item in client.published]
        assert statuses == ["accepted", "executed"]
        assert simulator.model.command_count == 1

        replay = FakeClient([envelope])
        await simulator._command_receive_loop(replay)
        replay_publisher = asyncio.create_task(simulator._ack_publish_loop(replay))
        await asyncio.wait_for(simulator.ack_queue.join(), timeout=2)
        replay_publisher.cancel()
        await asyncio.gather(replay_publisher, return_exceptions=True)
        assert [item[1]["payload"]["status"] for item in replay.published] == ["executed"]
        assert simulator.model.command_count == 1

    asyncio.run(exercise())


def test_command_queue_has_firmware_capacity(tmp_path):
    async def exercise():
        simulator = FirmwareSimulator(make_args(tmp_path))
        for index in range(COMMAND_QUEUE_LENGTH):
            await simulator.command_queue.put((command_envelope(f"q{index}", "led.on")["payload"], "trace"))
        client = FakeClient([command_envelope("overflow", "led.on")])
        await simulator._command_receive_loop(client)
        ack_publisher = asyncio.create_task(simulator._ack_publish_loop(client))
        await asyncio.wait_for(simulator.ack_queue.join(), timeout=2)
        ack_publisher.cancel()
        await asyncio.gather(ack_publisher, return_exceptions=True)
        ack = client.published[0][1]["payload"]
        assert ack["status"] == "rejected"
        assert ack["error_code"] == "device_rejected"

    asyncio.run(exercise())


def test_nvs_persists_priority_and_last_terminal_acks_only(tmp_path):
    store = SimulatorStateStore(tmp_path, "esp32s3-test")
    model = FirmwareModel("esp32s3-test")
    model.state["control_priority"] = "auto_first"
    model.state["window_open"] = True
    for index in range(TERMINAL_ACK_CACHE_SIZE + 3):
        model.remember_terminal_ack({"command_id": f"c{index}", "status": "executed"})
    store.save_nvs(model.nvs_snapshot())

    restarted = FirmwareModel("esp32s3-test", nvs=store.load_nvs())
    assert restarted.state["control_priority"] == "auto_first"
    assert restarted.state["window_open"] is False
    assert len(restarted.terminal_acks) == TERMINAL_ACK_CACHE_SIZE
    assert "c0" not in restarted.terminal_acks
    assert restarted.boot_id != model.boot_id


def test_image_failure_is_fail_soft(tmp_path, monkeypatch):
    async def exercise():
        simulator = FirmwareSimulator(make_args(tmp_path, no_image=False, image_interval=0.01))

        async def fail_upload(*_args, **_kwargs):
            raise RuntimeError("gateway unavailable")

        monkeypatch.setattr("tools.firmware_simulator.runtime.upload_image", fail_upload)
        task = asyncio.create_task(simulator._image_loop())
        await asyncio.sleep(0.03)
        simulator.stop_event.set()
        await asyncio.wait_for(task, timeout=1)
        assert simulator.last_image_error == "gateway unavailable"
        assert simulator.model.image_count == 0

    asyncio.run(exercise())


def test_mqtt_supervisor_reconnects_after_transport_failure(tmp_path, monkeypatch):
    async def exercise():
        simulator = FirmwareSimulator(make_args(tmp_path))
        attempts = 0

        class Connection:
            async def __aenter__(self):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise OSError("broker restarting")
                return FakeClient()

            async def __aexit__(self, *_args):
                return False

        async def finish_connection(_client):
            simulator.stop_event.set()

        monkeypatch.setattr("tools.firmware_simulator.runtime.mqtt_client", lambda *_args: Connection())
        monkeypatch.setattr("tools.firmware_simulator.runtime.RECONNECT_DELAYS", (0.01,))
        monkeypatch.setattr(simulator, "_run_connection", finish_connection)
        await asyncio.wait_for(simulator._mqtt_supervisor(), timeout=1)
        assert attempts == 2

    asyncio.run(exercise())


def test_connection_publishes_retained_status_and_capabilities(tmp_path):
    async def exercise():
        simulator = FirmwareSimulator(make_args(tmp_path))
        simulator.stop_event.set()
        client = FakeClient()
        await simulator._run_connection(client)
        retained = [(topic, options.get("retain")) for topic, _payload, options in client.published]
        assert ("devices/esp32s3-test/status", True) in retained
        assert ("devices/esp32s3-test/capabilities", True) in retained

    asyncio.run(exercise())
