from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_pose_estimator
from app.services.image_storage import save_image_bytes_from_upload
from app.services.pose_service import PoseEstimator, record_pose_detection

router = APIRouter(prefix="/api", tags=["pose"])


@router.post("/detect_pose")
async def detect_pose(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    estimator: PoseEstimator = Depends(get_pose_estimator),
):
    original = await save_image_bytes_from_upload(file, prefix="capture")
    if not estimator.available:
        record_pose_detection(
            db=db,
            pose="姿态检测服务未加载",
            human_presence="unknown",
            image_url=original.url,
            pose_image_url=None,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=estimator.error or "姿态检测模型不可用",
        )

    result = estimator.detect(original.path)
    event = record_pose_detection(
        db=db,
        pose=result.pose,
        human_presence=result.human_presence,
        image_url=original.url,
        pose_image_url=result.pose_image_url,
    )

    if result.human_presence == "no":
        return {
            "status": "no_pose",
            "message": result.pose,
            "human_presence": "no",
            "image_url": original.url,
            "photo_time": event.photo_time.isoformat(),
        }

    return {
        "status": "success",
        "pose": result.pose,
        "human_presence": result.human_presence,
        "image_url": original.url,
        "pose_image_url": result.pose_image_url,
        "landmarks_count": result.landmarks_count,
        "photo_time": event.photo_time.isoformat(),
    }
