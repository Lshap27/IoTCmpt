from fastapi import APIRouter

from app.api.routes import cloud, commands, images, pose, sensor

api_router = APIRouter()


@api_router.get("/")
def read_root():
    return {"message": "宿智云 API 运行成功", "version": "2.0.0"}


@api_router.get("/health")
def health():
    return {"status": "ok"}


api_router.include_router(sensor.router)
api_router.include_router(images.router)
api_router.include_router(pose.router)
api_router.include_router(commands.router)
api_router.include_router(cloud.router)
