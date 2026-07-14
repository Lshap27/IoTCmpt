from __future__ import annotations

import importlib.util
from pathlib import Path

PANEL_SERVER = Path(__file__).resolve().parents[2] / "tools" / "panel" / "panel_server.py"
SPEC = importlib.util.spec_from_file_location("iotcmpt_panel_server", PANEL_SERVER)
assert SPEC and SPEC.loader
panel_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(panel_server)


def test_panel_uses_recommended_values_when_sdkconfig_is_missing(tmp_path, monkeypatch):
    defaults = tmp_path / "sdkconfig.defaults"
    defaults.write_text(
        'CONFIG_APP_DEVICE_ID="esp32s3-001"\nCONFIG_APP_SENSOR_INTERVAL_MS=2500\nCONFIG_APP_WIFI_ENABLED=n\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(panel_server, "SDKCONFIG", tmp_path / "sdkconfig")
    monkeypatch.setattr(panel_server, "SDKCONFIG_DEFAULTS", defaults)

    values = panel_server.read_sdkconfig_values()

    assert values["CONFIG_APP_SENSOR_MOCK_ENABLED"] is False
    assert values["CONFIG_APP_WIFI_ENABLED"] is False
    assert values["CONFIG_APP_LED_ENABLED"] is False
    assert values["CONFIG_APP_LED_GPIO"] == "41"


def test_firmware_preflight_rejects_duplicate_gpio(tmp_path, monkeypatch):
    monkeypatch.setattr(panel_server, "SDKCONFIG", tmp_path / "sdkconfig")
    monkeypatch.setattr(panel_server, "SDKCONFIG_DEFAULTS", tmp_path / "sdkconfig.defaults")

    result = panel_server.firmware_preflight(
        {
            "CONFIG_APP_LED_ENABLED": True,
            "CONFIG_APP_LED_GPIO": 41,
            "CONFIG_APP_BUTTON_ENABLED": True,
            "CONFIG_APP_BUTTON_GPIO": 41,
        }
    )

    assert result["ok"] is False
    assert any("GPIO41" in error for error in result["errors"])


def test_existing_sdkconfig_explicit_values_win(tmp_path, monkeypatch):
    sdkconfig = tmp_path / "sdkconfig"
    sdkconfig.write_text(
        "# CONFIG_APP_WIFI_ENABLED is not set\n# CONFIG_APP_LED_ENABLED is not set\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(panel_server, "SDKCONFIG", sdkconfig)
    monkeypatch.setattr(panel_server, "SDKCONFIG_DEFAULTS", tmp_path / "sdkconfig.defaults")

    values = panel_server.read_sdkconfig_values()

    assert values["CONFIG_APP_WIFI_ENABLED"] is False
    assert values["CONFIG_APP_LED_ENABLED"] is False


def test_saving_firmware_config_removes_legacy_led_mode(tmp_path, monkeypatch):
    sdkconfig = tmp_path / "sdkconfig"
    sdkconfig.write_text(
        "CONFIG_APP_LED_MODE_LOGICAL=y\n# CONFIG_APP_LED_MODE_GPIO is not set\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(panel_server, "SDKCONFIG", sdkconfig)
    monkeypatch.setattr(panel_server, "SDKCONFIG_DEFAULTS", tmp_path / "sdkconfig.defaults")

    panel_server.save_firmware_config({"values": {"CONFIG_APP_LED_ENABLED": True, "CONFIG_APP_LED_GPIO": 41}})

    text = sdkconfig.read_text(encoding="utf-8")
    assert "CONFIG_APP_LED_MODE" not in text
    assert "CONFIG_APP_LED_ENABLED=y" in text
    assert "CONFIG_APP_LED_GPIO=41" in text
