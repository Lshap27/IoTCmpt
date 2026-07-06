from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    uploads = tmp_path / "uploads"
    monkeypatch.setenv("AIOT_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AIOT_UPLOADS_DIR", str(uploads))
    monkeypatch.setenv("AIOT_BASE_URL", "http://testserver")
    monkeypatch.setenv("AIOT_MQTT_ENABLED", "false")

    from app.core import config

    config.get_settings.cache_clear()

    for module_name in ["app.db.session", "app.main"]:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

