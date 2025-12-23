from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import create_db_and_tables, get_session
from app.core.security import get_password_hash
from app.models import User, UserRole, Gender, StudentProfile, StaffProfile
from app.models import Class, Subject, AcademicSession, Term
from datetime import date
from sqlmodel import Session, select

# Import routes
import sys
sys.path.append('..')  # Temporary - to import old routes

from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.bulk_upload import router as bulk_uploads_router
from app.api.v1 import dashboard as dashboard_router
from app.api.v1 import academic as academic_router
from app.api.v1 import enrollments as enrollment_router
from app.api.v1 import activity_logs as activity_logs_router
from app.api.v1 import results as results_router
from app.api.v1 import fees as fees_router
from app.api.v1 import payments as payments_router

# Create FastAPI app
app = FastAPI(
    title="School Management System API",
    description="A comprehensive school management system with authentication",
    version="1.0.0"
)

# Add CORS middleware - MUST be added before routes
# This fixes the "No 'Access-Control-Allow-Origin' header" error
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,  # Now properly parsed as List[str]
    allow_credentials=settings.CORS_CREDENTIALS,
    allow_methods=settings.CORS_METHODS,
    allow_headers=settings.CORS_HEADERS,
    expose_headers=["*"],  # Allow frontend to access all response headers
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Include routes - Same prefixes and tags as original
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(users_router, prefix="/admin", tags=["User Management"])
app.include_router(bulk_uploads_router)
app.include_router(dashboard_router.router, prefix="/admin")
app.include_router(academic_router.router)
app.include_router(enrollment_router.router)
app.include_router(activity_logs_router.router)
app.include_router(results_router.router)
app.include_router(fees_router.router)
app.include_router(payments_router.router)


@app.on_event("startup")
def on_startup():
    """Initialize database and create sample data"""
    create_db_and_tables()
    create_sample_data()


def create_sample_data():
    """
    Create sample users for testing.
    PRESERVED: Exact same sample data as original.
    """
    with next(get_session()) as session:
        # Check if admin already exists
        existing_admin = session.exec(
            select(User).where(User.email == "admin@school.com")
        ).first()
        if existing_admin:
            return
        
        # Create sample admin
        admin = User(
            username="admin",
            email="admin@school.com",
            phone="+2348012345678",
            password_hash=get_password_hash("admin123"),
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
            password_hash=get_password_hash("teacher123"),
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
            password_hash=get_password_hash("student123"),
            role=UserRole.student,
            first_name="Jane",
            last_name="Smith",
            gender=Gender.female,
            date_of_birth=date(2008, 3, 20)
        )
        session.add(student)
        
        session.commit()
        session.refresh(admin)
        session.refresh(teacher)
        session.refresh(student)
        
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
        session.commit()
        session.refresh(session_2024)
        
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
        session.commit()
        session.refresh(class_jss1a)
        
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
        
        session.commit()
        print("✅ Sample data created successfully!")
        print("🔐 Login Credentials:")
        print("   Admin: admin@school.com / admin123")
        print("   Teacher: teacher@school.com / teacher123")
        print("   Student: student@school.com / student123")


# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "School Management System API",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "active"
    }


# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": "2024-01-01"}


if __name__ == "__main__":
    import uvicorn
    
    print("🚀 Starting School Management System API...")
    print(f"🌐 CORS Origins: {settings.CORS_ORIGINS}")
    print("📖 API Documentation: http://localhost:8000/docs")
    print("🔗 Interactive API: http://localhost:8000/redoc")
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )