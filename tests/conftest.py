# tests/conftest.py
import sys
from pathlib import Path

# --- Configuración del Path (sin cambios) ---
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import os
import uuid

import pytest
import pytest_asyncio
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Generator

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ASYNC_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "local-only-test-secret-key-do-not-use")

from app.main import app
from app.db.session import Base
from app.db.session_async import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.user import User

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

sync_engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)

# ---------- Fixtures ----------
@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Crea las tablas en SQLite solo una vez por sesión de tests."""
    
    Base.metadata.create_all(bind=sync_engine)
    yield
    Base.metadata.drop_all(bind=sync_engine)

@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with sync_engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())

@pytest.fixture(scope="function")
def db_session() -> Generator[Session, any, None]:
    """Provee una sesión corta para pruebas unitarias."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()

@pytest_asyncio.fixture(scope="function")
async def client():
    """Provee un AsyncClient enlazado a la app sin overrides adicionales."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def async_db_session() -> AsyncSession:
    """Provee una AsyncSession para pruebas asíncronas directas."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()


# --- Fixtures de Usuarios (Sincrónicas, usan la sesión transaccional) ---

@pytest.fixture(scope="function")
def admin_user(db_session: Session) -> User:
    """Crea un usuario admin DENTRO de la transacción del test."""
    admin = User(
        email=f"admin-{uuid.uuid4()}@example.com",
        full_name="Test Admin",
        hashed_password=get_password_hash("Admin1234"),
        is_superuser=True,
        is_active=True,
        email_verified=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin

@pytest.fixture(scope="function")
def manager_user(db_session: Session) -> User:
    """Crea un usuario 'manager' DENTRO de la transacción del test."""
    manager = User(
        email=f"manager-{uuid.uuid4()}@example.com",
        full_name="Test Manager",
        hashed_password=get_password_hash("Manager1234"),
        is_superuser=False,
        is_active=True,
        email_verified=True,
    )
    db_session.add(manager)
    db_session.commit()
    db_session.refresh(manager)
    return manager

# vvv --- FIXTURES AÑADIDAS --- vvv
@pytest.fixture(scope="function")
def normal_user(db_session: Session) -> User:
    """Crea un usuario normal DENTRO de la transacción del test."""
    user = User(
        email=f"user-{uuid.uuid4()}@example.com",
        full_name="Test User",
        hashed_password=get_password_hash("User1234"),
        is_superuser=False,
        is_active=True,
        email_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user
# ^^^ ------------------------- ^^^

# --- Fixtures de Tokens (Asíncronas, dependen de las fixtures de usuario) ---

@pytest_asyncio.fixture(scope="function")
async def admin_token(client: httpx.AsyncClient, admin_user: User) -> str:
    """Devuelve un access token válido para el admin."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": admin_user.email, "password": "Admin1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]

@pytest_asyncio.fixture(scope="function")
async def manager_token(client: httpx.AsyncClient, manager_user: User) -> str:
    """Devuelve un token para el 'manager'."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": manager_user.email, "password": "Manager1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]

@pytest_asyncio.fixture(scope="function")
async def user_token(client: httpx.AsyncClient, normal_user: User) -> str:
    """Devuelve un token para un usuario normal."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": normal_user.email, "password": "User1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]
# ^^^ ------------------------- ^^^
