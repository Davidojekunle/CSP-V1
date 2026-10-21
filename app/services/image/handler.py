# app/services/image/handler.py
"""
Service for handling image uploads to a cloud provider (e.g., Cloudinary).
The Cloudinary SDK is synchronous, so calls run in a worker thread to keep
the event loop free.
"""
import logging

import cloudinary
import cloudinary.uploader
from anyio.to_thread import run_sync
from fastapi import UploadFile, HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

# --- Configure Cloudinary from central settings ---
cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True
)


async def upload_profile_picture(file: UploadFile, user_id: str) -> str:
    """
    Uploads a profile picture to Cloudinary, overwriting any existing one for the user.
    """
    public_id = f"profile_pictures/{user_id}"
    try:
        upload_result = await run_sync(
            lambda: cloudinary.uploader.upload(file.file, public_id=public_id, overwrite=True, resource_type="image")
        )
        return upload_result.get('secure_url')
    except Exception as e:
        logger.exception("Cloudinary upload failed for %s", public_id)
        raise HTTPException(status_code=500, detail=f"Failed to upload image to cloud: {e}")


async def delete_profile_picture(user_id: str):
    """
    Deletes a user's profile picture from Cloudinary.
    """
    public_id = f"profile_pictures/{user_id}"
    try:
        await run_sync(cloudinary.uploader.destroy, public_id)
    except Exception:
        logger.exception("Error deleting image from cloud for public_id %s", public_id)
