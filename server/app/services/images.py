from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import models
from app.services.commands import ensure_device

# device_id 会作为 uploads/ 下的目录名，必须限制字符集以防路径穿越
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def prune_images(db: Session, settings: Settings, device_id: str) -> None:
    """Keep only the newest configured number of image assets per device."""
    limit = settings.max_images_per_device
    if limit <= 0:
        return
    expired = (
        db.query(models.ImageAsset)
        .filter(models.ImageAsset.device_id == device_id)
        .order_by(models.ImageAsset.created_at.desc(), models.ImageAsset.id.desc())
        .offset(limit)
        .all()
    )
    if not expired:
        return

    expired_ids = [asset.id for asset in expired]
    db.query(models.PoseResult).filter(
        or_(
            models.PoseResult.source_image_id.in_(expired_ids),
            models.PoseResult.annotated_image_id.in_(expired_ids),
        )
    ).delete(synchronize_session=False)
    paths = [settings.uploads_dir / asset.device_id / asset.filename for asset in expired]
    for asset in expired:
        db.delete(asset)
    db.commit()
    for path in paths:
        path.unlink(missing_ok=True)


def save_image(
    db: Session, settings: Settings, device_id: str, file: UploadFile, *, kind: str = "capture"
) -> models.ImageAsset:
    if file.content_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(status_code=415, detail="Only JPEG images are supported")
    if not DEVICE_ID_PATTERN.fullmatch(device_id):
        raise HTTPException(status_code=400, detail="Invalid device id")

    ensure_device(db, device_id)
    device_dir = settings.uploads_dir / device_id
    device_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.jpg"
    path = device_dir / filename

    size = 0
    too_large = False
    with path.open("wb") as handle:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                too_large = True
                break
            handle.write(chunk)
    if too_large:
        # Windows 上不能删除仍被打开的文件，必须先关闭句柄再清理
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail="Image upload is too large")

    relative = Path("uploads") / device_id / filename
    asset = models.ImageAsset(
        device_id=device_id,
        filename=filename,
        url=f"{settings.base_url}/{relative.as_posix()}",
        content_type=file.content_type or "image/jpeg",
        size_bytes=size,
        kind=kind,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    prune_images(db, settings, device_id)
    return asset
