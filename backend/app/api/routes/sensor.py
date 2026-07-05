from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas import SensorUpload
from app.services.sensor_service import (
    create_sensor_reading,
    latest_payload,
    list_history_payloads,
    summary_payload,
)

router = APIRouter(prefix="/api", tags=["sensor"])


@router.post("/upload_sensor")
def upload_sensor(data: SensorUpload, db: Session = Depends(get_db)):
    create_sensor_reading(db, data)
    return {"status": "success", "message": "数据上报成功"}


@router.get("/latest")
def get_latest(db: Session = Depends(get_db)):
    payload = latest_payload(db)
    if payload is None:
        return {"error": "暂无数据，请等待传感器上报"}
    return payload


@router.get("/history")
def get_history(
    limit: int = Query(default=10, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return list_history_payloads(db, limit)


@router.get("/summary")
def get_summary(db: Session = Depends(get_db)):
    payload = summary_payload(db)
    if payload is None:
        raise HTTPException(status_code=404, detail="暂无数据")
    return payload
