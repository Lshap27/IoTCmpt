from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.services.pose_service import PoseEstimator


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)

    app.state.pose_estimator = PoseEstimator(settings.pose_model_path)
    app.state.pose_estimator.load()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="宿智云 - 宿舍健康治理平台 API",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    settings.images_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/images", StaticFiles(directory=str(settings.images_dir)), name="images")
    app.include_router(api_router)
    return app


app = create_app()
