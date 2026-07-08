from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import models
from app.services.commands import ensure_device


def save_image(db: Session, settings: Settings, device_id: str, file: UploadFile) -> models.ImageAsset:
    if file.content_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(status_code=415, detail="Only JPEG images are supported")

    ensure_device(db, device_id)
    device_dir = settings.uploads_dir / device_id
    device_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.jpg"
    path = device_dir / filename

    size = 0
    with path.open("wb") as handle:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Image upload is too large")
            handle.write(chunk)

    relative = Path("uploads") / device_id / filename
    asset = models.ImageAsset(
        device_id=device_id,
        filename=filename,
        url=f"{settings.base_url}/{relative.as_posix()}",
        content_type=file.content_type or "image/jpeg",
        size_bytes=size,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset
