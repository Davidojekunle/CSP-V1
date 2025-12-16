import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, SQLModel
from sqlmodel.pool import StaticPool

from app.main import app
from app.core.database import get_session
from app.core.security import get_password_hash
from app.models import User, UserRole, Gender
from datetime import date


@pytest.fixture(name="session")
def session_fixture():
    """Create a test database session"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    """Create a test client"""
    def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="test_admin")
def test_admin_fixture(session: Session):
    """Create test admin user"""
    admin = User(
        username="testadmin",
        email="testadmin@test.com",
        phone="+2348012345678",
        password_hash=get_password_hash("testpass123"),
        role=UserRole.admin,
        first_name="Test",
        last_name="Admin",
        gender=Gender.male,
        date_of_birth=date(1990, 1, 1)
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    return admin


@pytest.fixture(name="admin_token")
def admin_token_fixture(client: TestClient):
    """Get admin authentication token"""
    response = client.post(
        "/auth/token",
        data={"username": "testadmin@test.com", "password": "testpass123"}
    )
    return response.json()["access_token"]