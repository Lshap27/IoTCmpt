from __future__ import annotations

from fastapi import HTTPException, Request

from app.application.automation import AiRunApplicationService, AutomationApplicationService
from app.application.commands import CommandApplicationService
from app.application.queries import DeviceQueryApplicationService
from app.services.pose import PoseService


def get_pose_service(request: Request) -> PoseService:
    pose = getattr(request.app.state, "pose_service", None)
    if pose is None:
        raise HTTPException(status_code=503, detail="Pose service is not available")
    return pose


def get_command_application(request: Request) -> CommandApplicationService:
    service = getattr(request.app.state, "command_application", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Command application is not available")
    return service


def get_automation_application(request: Request) -> AutomationApplicationService:
    service = getattr(request.app.state, "automation_application", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Automation application is not available")
    return service


def get_ai_run_application(request: Request) -> AiRunApplicationService:
    service = getattr(request.app.state, "ai_run_application", None)
    if service is None:
        raise HTTPException(status_code=503, detail="AI run application is not available")
    return service


def get_device_queries(request: Request) -> DeviceQueryApplicationService:
    service = getattr(request.app.state, "device_queries", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Device query application is not available")
    return service
