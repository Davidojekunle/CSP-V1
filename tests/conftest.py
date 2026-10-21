import os

# Settings are read at import time; make the test environment explicit and offline
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz")
os.environ["ENVIRONMENT"] = "test"
os.environ["AUTO_CREATE_TABLES"] = "false"
os.environ["SEED_SAMPLE_DATA"] = "false"
os.environ["EMAIL_ENABLED"] = "false"
os.environ["PAYSTACK_SECRET_KEY"] = "sk_test_dummy"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./.pytest-unused.db"

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from app.main import app  # noqa: E402
from app.core.database import get_session  # noqa: E402
from app.core.auth import create_access_token  # noqa: E402
from app.models import (  # noqa: E402
    User, UserRole, Gender, StudentProfile, StaffProfile, AcademicSession, Term, TermName, Class, Subject,
    ClassSubject, Enrollment,
)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD = "testpass123"
_PASSWORD_HASH = _pwd.hash(PASSWORD)


def _fk_on(engine):
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys = ON")


@pytest.fixture(name="db_path")
def db_path_fixture(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture(name="session")
def session_fixture(db_path):
    """Sync session on the same SQLite file the app uses, for arranging/asserting data."""
    engine = create_engine(f"sqlite:///{db_path}")
    _fk_on(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


@pytest.fixture(name="client")
def client_fixture(db_path, session):
    """TestClient whose requests use an async engine on the test database."""
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    _fk_on(async_engine.sync_engine)
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def get_session_override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def make_user(session, username, email, role, first="Test", last="User", phone=None):
    user = User(
        username=username, email=email, phone=phone or f"+234{abs(hash(email)) % 10**10:010d}",
        password_hash=_PASSWORD_HASH, role=role, first_name=first, last_name=last,
        gender=Gender.male, date_of_birth=date(1990, 1, 1),
    )
    session.add(user)
    session.commit()
    return user


def auth_header(user: User) -> dict:
    token = create_access_token({"sub": user.email, "user_type": user.role.value})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(name="test_admin")
def test_admin_fixture(session):
    """Create test admin user"""
    return make_user(session, "testadmin", "testadmin@test.com", UserRole.admin, "Test", "Admin", "+2348012345678")


@pytest.fixture(name="admin_token")
def admin_token_fixture(client: TestClient, test_admin):
    """Get admin authentication token"""
    response = client.post("/auth/token", data={"username": "testadmin@test.com", "password": PASSWORD})
    return response.json()["access_token"]


@pytest.fixture(name="school")
def school_fixture(session, test_admin):
    """A small school: one session/term, two classes (same form teacher), a subject, two students."""
    teacher = make_user(session, "teacher1", "teacher@test.com", UserRole.staff, "John", "Doe")
    session.add(StaffProfile(user_id=teacher.id, staff_no="TCH001", job_title="Teacher", employment_date=date(2020, 9, 1)))
    ac_session = AcademicSession(name="2024/2025", start_date=date(2024, 9, 1), end_date=date(2025, 7, 31), is_current=True)
    session.add(ac_session)
    session.commit()
    term = Term(session_id=ac_session.id, name=TermName.first, start_date=date(2024, 9, 1), end_date=date(2024, 12, 20), is_current=True)
    class_a = Class(name="JSS1 A", level="JSS1", arm="A", form_teacher_id=teacher.id)
    class_b = Class(name="SS2 A", level="SS2", arm="A", form_teacher_id=teacher.id)
    subject = Subject(code="MTH", name="Mathematics")
    session.add_all([term, class_a, class_b, subject])
    session.commit()
    session.add(ClassSubject(class_id=class_a.id, subject_id=subject.id, teacher_id=teacher.id))

    students = []
    for i, cls in enumerate([class_a, class_b]):
        s = make_user(session, f"student{i}", f"student{i}@test.com", UserRole.student, f"Stu{i}", f"Dent{i}")
        session.add(StudentProfile(user_id=s.id, admission_number=f"ADM{i:03d}", guardian_name="G", guardian_phone="+2348000000000",
                                   guardian_email="g@test.com", current_class_id=cls.id, enrollment_date=date(2024, 9, 1)))
        session.add(Enrollment(student_id=s.id, class_id=cls.id, session_id=ac_session.id, term_id=term.id,
                               enrolled_at=date(2024, 9, 1), is_active=True))
        students.append(s)
    session.commit()
    return {"admin": test_admin, "teacher": teacher, "session": ac_session, "term": term,
            "class_a": class_a, "class_b": class_b, "subject": subject, "students": students}
