# app/services/image/handler.py
"""
Service for handling image uploads to a cloud provider (e.g., Cloudinary).
"""
from fastapi import UploadFile, HTTPException
import cloudinary
import cloudinary.uploader

from app.core.config import settings

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
        upload_result = cloudinary.uploader.upload(
            file.file, public_id=public_id, overwrite=True, resource_type="image"
        )
        return upload_result.get('secure_url')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload image to cloud: {e}")

async def delete_profile_picture(user_id: str):
    """
    Deletes a user's profile picture from Cloudinary.
    """
    public_id = f"profile_pictures/{user_id}"
    try:
        cloudinary.uploader.destroy(public_id)
    except Exception as e:
        print(f"Error deleting image from cloud for public_id {public_id}: {e}")