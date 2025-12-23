# app/core/config.py
"""
Centralized configuration management.
Replaces scattered os.getenv() calls throughout the codebase.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List
from functools import lru_cache
from pydantic import field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    APP_NAME: str = "School Management System API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Database - PostgreSQL (future)
    POSTGRES_USER: Optional[str] = None
    POSTGRES_PASSWORD: Optional[str] = None
    POSTGRES_HOST: Optional[str] = None
    POSTGRES_PORT: Optional[str] = None
    POSTGRES_DB: Optional[str] = None
    
    # Database URL (constructed or direct)
    DATABASE_URL: str = "sqlite:///school_management.db"
    
    # SQLite legacy path
    SQLITE_DB_PATH: str = "school_management.db"
    
    # JWT Authentication (CRITICAL - preserve exact behavior)
    SECRET_KEY: str  # Required
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 60 * 24 = 1 day (matches original)
    
    # CORS Settings
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://172.20.10.3:5173",
        "https://school-dashboard-pink.vercel.app"
    ]
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: List[str] = ["*"]
    CORS_HEADERS: List[str] = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            if v.strip() == "*":
                return ["*"]
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v
    
    # Email Configuration (FastAPI-Mail)
    MAIL_USERNAME: Optional[str] = None
    MAIL_PASSWORD: Optional[str] = None
    MAIL_FROM: Optional[str] = None
    MAIL_PORT: int = 587
    MAIL_SERVER: Optional[str] = None
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False
    EMAIL_ENABLED: bool = False
    
    # File Upload & Storage
    # Cloudinary Integration (for image uploads)
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None

    
    # PDF Generation
    PDF_TEMPLATE_DIR: str = "templates/pdf"
    PDF_OUTPUT_DIR: str = "outputs/pdf"
    PDF_LOGO_PATH: str = "school_logo.png"
    
    # Paystack Integration
    PAYSTACK_SECRET_KEY: Optional[str] = None
    PAYSTACK_PUBLIC_KEY: Optional[str] = None
    PAYSTACK_CALLBACK_URL: Optional[str] = None
    
    # Activity Logging
    ACTIVITY_LOG_ENABLED: bool = True
    
    # Security
    ALLOWED_HOSTS: List[str] = ["*"]
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )
    
    def get_database_url(self) -> str:
        """Get database URL."""
        return self.DATABASE_URL
    
    def get_postgres_url(self) -> Optional[str]:
        """Construct PostgreSQL URL if credentials provided."""
        if all([
            self.POSTGRES_USER,
            self.POSTGRES_PASSWORD,
            self.POSTGRES_HOST,
            self.POSTGRES_PORT,
            self.POSTGRES_DB
        ]):
            return (
                f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        return None
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"
    
    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() == "development"


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache to ensure settings are loaded only once.
    """
    return Settings()


# Global settings instance
settings = get_settings()