import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("psycopg")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


def test_live_returns_200() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_ready_returns_503_when_db_down() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "database_unavailable"
    assert set(body["error"]) == {"code", "message", "details"}


def test_ready_returns_200_with_db(test_database_url: str, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import get_settings
    from app.core.database import get_engine

    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        response = TestClient(create_app()).get("/api/v1/health/ready")
    finally:
        get_settings.cache_clear()
        get_engine.cache_clear()
    assert response.status_code == 200
