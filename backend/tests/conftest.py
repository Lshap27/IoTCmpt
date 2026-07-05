import os
from pathlib import Path

os.environ.setdefault("APP_DATABASE_URL", "sqlite:///./test_backend.db")
os.environ.setdefault("APP_AUTO_CREATE_TABLES", "true")
os.environ.setdefault("APP_BASE_URL", "http://testserver")
os.environ.setdefault("APP_IMAGES_DIR", "./test_images")
os.environ.setdefault("APP_LLM_ENDPOINT", "")
os.environ.setdefault("APP_LLM_API_KEY", "")

from fastapi.testclient import TestClient
import pytest

from app.db.base import Base
from app.db.session import engine
from app.main import app


@pytest.fixture(autouse=True)
def reset_db(tmp_path):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def tiny_jpeg() -> bytes:
    return bytes.fromhex(
        "ffd8ffe000104a46494600010101006000600000"
        "ffdb0043000302020302020303030304030304050805050404050a070706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016101113141515150c0f171816141812141514"
        "ffdb00430103040405040509050509140d0b0d141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414141414"
        "ffc00011080001000103012200021101031101"
        "ffc4001400010000000000000000000000000000000000000008"
        "ffc4001410010000000000000000000000000000000000000000"
        "ffc4001401010000000000000000000000000000000000000000"
        "ffc4001411010000000000000000000000000000000000000000"
        "ffda000c03010002110311003f00b2c001ffd9"
    )
