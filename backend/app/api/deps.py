from __future__ import annotations

from collections.abc import Generator
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.llm_service import LLMClient

bearer = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_device_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> None:
    if not settings.device_token:
        return
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing device token")
    if credentials.credentials != settings.device_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid device token")


def get_llm_client() -> LLMClient:
    return LLMClient(settings)


def get_pose_estimator(request: Request):
    return request.app.state.pose_estimator
