from fastapi import APIRouter, File, UploadFile

from app.services.image_storage import save_uploaded_image

router = APIRouter(prefix="/api", tags=["images"])


@router.post("/upload_image")
async def upload_image(file: UploadFile = File(...)):
    stored = await save_uploaded_image(file)
    return {
        "status": "success",
        "image_url": stored.url,
        "filename": stored.filename,
    }
