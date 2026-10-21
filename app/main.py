import logging
from contextlib import asynccontextmanager
from datetime import date, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.engine import make_url
from sqlmodel import select

from app.core.config import settings
from app.core.my_logging import setup_logging
from app.core.database import create_db_and_tables, AsyncSessionFactory, async_engine, check_database_connection
from app.core.security import get_password_hash
from app.models import User, UserRole, Gender, StudentProfile, StaffProfile
from app.models import Class, Subject, AcademicSession, Term

from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.bulk_upload import router as bulk_uploads_router
from app.api.v1 import dashboard as dashboard_router
from app.api.v1 import academic as academic_router
from app.api.v1 import enrollments as enrollment_router
from app.api.v1 import activity_logs as activity_logs_router
from app.api.v1 import results as results_router
from app.api.v1.fees import router as admin_fees_router, student_router as student_fees_router, neutral_fee_router
from app.api.v1 import payments as payments_router
from app.api.v1.staff import router as staff_routes, traits_router
from app.api.v1.students import router as student_routes

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.is_production and settings.is_sqlite:
        # Without DATABASE_URL the app falls back to an empty local SQLite file; every
        # request would fail while health checks still pass. Refuse to start instead.
        raise RuntimeError(
            "ENVIRONMENT=production but DATABASE_URL is not set (falling back to SQLite). "
            "Set DATABASE_URL to the Supabase connection string in the host's environment variables."
        )
    db_url = make_url(settings.async_database_url)
    logger.info("Database: %s on %s:%s", db_url.get_backend_name(), db_url.host or "local file", db_url.port or "-")
    if settings.AUTO_CREATE_TABLES:
        await create_db_and_tables()
    if settings.SEED_SAMPLE_DATA:
        await create_sample_data()
    if settings.is_production and len(settings.SECRET_KEY) < 32:
        logger.warning("SECRET_KEY is shorter than 32 characters; use a long random value in production.")
    logger.info("Startup complete (environment=%s)", settings.ENVIRONMENT)
    yield
    await async_engine.dispose()


# Create FastAPI app
app = FastAPI(
    title="School Management System API",
    description="A comprehensive school management system with authentication",
    version="1.0.0",
    lifespan=lifespan,
)

# Compress large JSON responses (lists of students, invoices, results)
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Add CORS middleware - PRESERVED: Same origins as original
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_CREDENTIALS,
    allow_methods=settings.CORS_METHODS,
    allow_headers=settings.CORS_HEADERS,
)

# # Include routes - PRESERVED: Same prefixes and tags
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(users_router, prefix="/admin", tags=["User Management"])
app.include_router(bulk_uploads_router)
app.include_router(dashboard_router.router, prefix="/admin")
app.include_router(academic_router.router)
app.include_router(enrollment_router.router)
app.include_router(activity_logs_router.router)
app.include_router(results_router.router)
app.include_router(admin_fees_router)
app.include_router(student_fees_router)
app.include_router(payments_router.router)
app.include_router(staff_routes)
app.include_router(traits_router)
app.include_router(student_routes)
app.include_router(neutral_fee_router)


async def create_sample_data():
    """
    Create sample users for local development (SEED_SAMPLE_DATA).
    Never enabled by default in production: these accounts have known passwords.
    """
    async with AsyncSessionFactory() as session:
        # Check if admin already exists
        result = await session.execute(
            select(User).where(User.email == "admin@school.com")
        )
        existing_admin = result.scalars().first()
        if existing_admin:
            return
        
        # Create sample admin
        admin = User(
            username="admin",
            email="admin@school.com",
            phone="+2348012345678",
            password_hash= await  get_password_hash("admin123"),
            role=UserRole.admin,
            first_name="System",
            last_name="Administrator",
            gender=Gender.other,
            date_of_birth=date(1980, 1, 1)
        )
        session.add(admin)
        
        # Create sample teacher
        teacher = User(
            username="teacher1",
            email="teacher@school.com",
            phone="+2348012345679",
            password_hash=await get_password_hash("teacher123"),
            role=UserRole.staff,
            first_name="John",
            last_name="Doe",
            gender=Gender.male,
            date_of_birth=date(1985, 5, 15)
        )
        session.add(teacher)
        
        # Create sample student
        student = User(
            username="student1",
            email="student@school.com",
            phone="+2348012345680",
            password_hash=await get_password_hash("student123"),
            role=UserRole.student,
            first_name="Jane",
            last_name="Smith",
            gender=Gender.female,
            date_of_birth=date(2008, 3, 20)
        )
        session.add(student)
        
        await session.commit()
        await session.refresh(admin)
        await session.refresh(teacher)
        await session.refresh(student)
        
        # Create teacher profile
        teacher_profile = StaffProfile(
            user_id=teacher.id,
            staff_no="TCH001",
            job_title="Mathematics Teacher",
            employment_date=date(2020, 9, 1)
        )
        session.add(teacher_profile)
        
        # Create academic session and term
        session_2024 = AcademicSession(
            name="2024/2025",
            start_date=date(2024, 9, 1),
            end_date=date(2025, 7, 31),
            is_current=True
        )
        session.add(session_2024)
        await session.commit()
        await session.refresh(session_2024)
        
        first_term = Term(
            session_id=session_2024.id,
            name="First",
            start_date=date(2024, 9, 1),
            end_date=date(2024, 12, 20),
            is_current=True
        )
        session.add(first_term)
        
        # Create sample class
        class_jss1a = Class(
            name="JSS1 A",
            level="JSS1",
            arm="A",
            form_teacher_id=teacher.id
        )
        session.add(class_jss1a)
        await session.commit()
        await session.refresh(class_jss1a)
        
        # Create student profile
        student_profile = StudentProfile(
            user_id=student.id,
            admission_number="STU001",
            guardian_name="Mr. Smith",
            guardian_phone="+2348012345681",
            guardian_email="guardian@email.com",
            current_class_id=class_jss1a.id,
            enrollment_date=date(2024, 9, 1)
        )
        session.add(student_profile)
        
        # Create sample subjects
        mathematics = Subject(code="MTH", name="Mathematics")
        english = Subject(code="ENG", name="English Language")
        session.add(mathematics)
        session.add(english)
        
        await session.commit()
        logger.info("Sample data created (admin@school.com, teacher@school.com, student@school.com)")


# Root endpoint - PRESERVED
@app.get("/")
async def root():
    return {
        "message": "School Management System API",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "active"
    }


# Health check endpoint - PRESERVED shape; also reports database connectivity
@app.get("/health")
async def health_check():
    if not await check_database_connection():
        return JSONResponse(status_code=503, content={"status": "unhealthy", "timestamp": datetime.utcnow().isoformat()})
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
