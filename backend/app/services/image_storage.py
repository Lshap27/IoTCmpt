from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
from fastapi import HTTPException, UploadFile

from app.core.config import settings

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


@dataclass(frozen=True)
class StoredImageResult:
    filename: str
    path: Path
    url: str


def _extension_for_content_type(content_type: str) -> str:
    if content_type in {"image/jpeg", "image/jpg"}:
        return "jpg"
    if content_type == "image/png":
        return "png"
    if content_type == "image/webp":
        return "webp"
    raise HTTPException(status_code=400, detail="不支持的文件格式")


def decode_image(content: bytes):
    data = np.frombuffer(content, np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="无法解析图片")
    return image


def cleanup_old_images() -> None:
    images_dir = settings.images_dir
    if not images_dir.exists():
        return

    files = [path for path in images_dir.iterdir() if path.is_file()]
    cutoff = datetime.now() - timedelta(days=settings.max_image_age_days)
    for path in files:
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                path.unlink()
        except OSError:
            continue

    files = [path for path in images_dir.iterdir() if path.is_file()]
    if len(files) <= settings.max_images:
        return
    files.sort(key=lambda item: item.stat().st_mtime)
    for path in files[: len(files) - settings.max_images]:
        try:
            path.unlink()
        except OSError:
            continue


def save_image_content(content: bytes, content_type: str, prefix: str = "image") -> StoredImageResult:
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=400, detail="文件过大")
    extension = _extension_for_content_type(content_type)
    decode_image(content)

    settings.images_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{prefix}_{uuid4()}.{extension}"
    path = settings.images_dir / filename
    path.write_bytes(content)
    cleanup_old_images()
    return StoredImageResult(filename=filename, path=path, url=f"{settings.base_url}/images/{filename}")


async def save_image_bytes_from_upload(file: UploadFile, prefix: str = "image") -> StoredImageResult:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="不支持的文件格式")
    content = await file.read()
    return save_image_content(content, file.content_type or "", prefix=prefix)


async def save_uploaded_image(file: UploadFile) -> StoredImageResult:
    return await save_image_bytes_from_upload(file, prefix="image")
