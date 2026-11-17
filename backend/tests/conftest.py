"""Every test runs against a fresh in-memory database with the real catalogue."""

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"
os.environ["LLM_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.recsys import state  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    state.reset()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db(client):
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def demo(client):
    """A client signed in as the seeded demo reader."""
    response = client.post("/api/auth/login", json={"username": "demo", "password": "demo1234"})
    assert response.status_code == 200
    return client


@pytest.fixture()
def newcomer(client):
    """A client signed in as a brand-new reader with no history."""
    response = client.post(
        "/api/auth/register",
        json={
            "name": "New Reader",
            "username": "newreader",
            "email": "new@example.com",
            "password": "correct-horse",
        },
    )
    assert response.status_code == 201
    return client


def isbn_of(client, title: str) -> str:
    items = client.get("/api/books", params={"q": title, "page_size": 60}).json()["items"]
    return next(b["isbn"] for b in items if b["title"] == title)
