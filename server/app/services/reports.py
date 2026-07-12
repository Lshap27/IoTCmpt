from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.timeutil import iso_utc
from app.db import models
from app.schemas import AiHealthReport, ReportPeriod
from app.services.llm import LLMService

PERIODS: dict[ReportPeriod, tuple[timedelta, int]] = {
    "hour": (timedelta(hours=1), 60),
    "day": (timedelta(days=1), 60 * 60),
    "week": (timedelta(days=7), 6 * 60 * 60),
}


def _avg(rows: list[models.Telemetry], field: str) -> float | None:
    values = [float(value) for row in rows if (value := getattr(row, field)) is not None]
    return sum(values) / len(values) if values else None


def _extreme(rows: list[models.Telemetry], field: str, fn: Callable[[list[float]], float]) -> float | None:
    values = [float(value) for row in rows if (value := getattr(row, field)) is not None]
    return fn(values) if values else None


def collect_report_context(db: Session, device_id: str, period: ReportPeriod) -> dict[str, Any]:
    duration, bucket_seconds = PERIODS[period]
    end = datetime.now(UTC).replace(tzinfo=None)
    start = end - duration
    rows = (
        db.query(models.Telemetry)
        .filter(models.Telemetry.device_id == device_id, models.Telemetry.sampled_at >= start)
        .order_by(models.Telemetry.sampled_at.asc())
        .all()
    )
    events = (
        db.query(models.DeviceEvent)
        .filter(models.DeviceEvent.device_id == device_id, models.DeviceEvent.created_at >= start)
        .all()
    )
    bucket_indexes = {int((row.sampled_at - start).total_seconds() // bucket_seconds) for row in rows}
    alert_bucket_indexes = {
        int((row.sampled_at - start).total_seconds() // bucket_seconds) for row in rows if row.air_quality == "alert"
    }
    expected = max(1, int(duration.total_seconds() // bucket_seconds))
    coverage = {
        "start": iso_utc(start),
        "end": iso_utc(end),
        "sample_count": len(rows),
        "bucket_count": len(bucket_indexes),
        "expected_bucket_count": expected,
        "completeness_percent": round(min(100.0, len(bucket_indexes) / expected * 100), 1),
    }
    metrics = {
        "temperature_avg_c": _avg(rows, "temperature_c"),
        "temperature_min_c": _extreme(rows, "temperature_c", min),
        "temperature_max_c": _extreme(rows, "temperature_c", max),
        "humidity_avg_percent": _avg(rows, "humidity_percent"),
        "tvoc_avg_ppb": _avg(rows, "tvoc_ppb"),
        "hcho_avg_ug_m3": _avg(rows, "hcho_ug_m3"),
        "eco2_avg_ppm": _avg(rows, "eco2_ppm"),
        "eco2_max_ppm": _extreme(rows, "eco2_ppm", max),
        "alert_bucket_count": len(alert_bucket_indexes),
        "smoke_event_count": sum(event.type == "smoke.detected" for event in events),
    }
    recent_points = [
        {
            "sampled_at": iso_utc(row.sampled_at),
            "temperature_c": row.temperature_c,
            "humidity_percent": row.humidity_percent,
            "tvoc_ppb": row.tvoc_ppb,
            "hcho_ug_m3": row.hcho_ug_m3,
            "eco2_ppm": row.eco2_ppm,
            "air_quality": row.air_quality,
            "smoke_detected": row.smoke_detected,
        }
        for row in rows[-48:]
    ]
    return {
        "device_id": device_id,
        "period": period,
        "operational_thresholds": {
            "humidity_high_percent": 75,
            "tvoc_watch_ppb": 300,
            "hcho_watch_ug_m3": 60,
            "eco2_watch_ppm": 1000,
            "note": "项目运维关注阈值，不等同于医疗诊断或法规限值",
        },
        "coverage": coverage,
        "metrics": metrics,
        "recent_points": recent_points,
    }


async def generate_health_report(db: Session, device_id: str, period: ReportPeriod, llm: LLMService) -> AiHealthReport:
    context = collect_report_context(db, device_id, period)
    if context["coverage"]["sample_count"] == 0:
        raise ValueError("所选时段没有遥测数据")
    result = await llm.generate_report(context)
    return AiHealthReport(
        device_id=device_id,
        period=period,
        generated_at=iso_utc(datetime.now(UTC)) or "",
        model="mock" if llm.settings.llm_endpoint == "mock" else llm.settings.llm_model,
        coverage=context["coverage"],
        metrics=context["metrics"],
        **result,
    )
