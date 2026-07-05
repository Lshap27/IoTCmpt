from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_llm_client, verify_device_token
from app.schemas import CloudCommandResponse, CloudExchangeRequest
from app.services.command_service import create_cloud_command_record
from app.services.llm_service import LLMClient

router = APIRouter(prefix="/api/cloud", tags=["cloud"])


@router.post(
    "/exchange",
    response_model=CloudCommandResponse,
    dependencies=[Depends(verify_device_token)],
)
def cloud_exchange(
    payload: CloudExchangeRequest,
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm_client),
):
    response = llm.exchange(payload)
    create_cloud_command_record(db, response)
    return response
