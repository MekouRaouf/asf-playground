import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("psycopg")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.shared.exceptions import NotFoundError  # noqa: E402
from app.shared.pagination import Page, PageParams  # noqa: E402


def _client() -> TestClient:
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise NotFoundError("nothing here", details={"id": 1})

    @app.get("/needs-int")
    def needs_int(n: int) -> int:
        return n

    return TestClient(app, raise_server_exceptions=False)


def test_app_error_format() -> None:
    response = _client().get("/boom")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "nothing here", "details": {"id": 1}}
    }


def test_unknown_route_format() -> None:
    response = _client().get("/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"


def test_validation_error_format() -> None:
    response = _client().get("/needs-int", params={"n": "x"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"] == ["query", "n"]


def test_page_schema() -> None:
    page = Page[int].create([1, 2], total=5, params=PageParams(page=1, size=2))
    assert page.model_dump() == {
        "items": [1, 2],
        "total": 5,
        "page": 1,
        "size": 2,
        "pages": 3,
    }
