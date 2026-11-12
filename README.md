# asf-playground

RelayDesk API (FastAPI + PostgreSQL 16 + SQLAlchemy 2 + Alembic).

## Run with Docker

```
cp .env.example .env   # set SECRET_KEY and passwords
docker compose up --build
docker compose run --rm api alembic upgrade head
curl localhost:8000/api/v1/health/live
curl localhost:8000/api/v1/health/ready   # 503 when the DB is down
```

## Develop

```
pip install -e ".[dev]"
pytest -q
ruff check . && mypy app && bandit -c pyproject.toml -r app
alembic upgrade head && alembic downgrade base
```

DB-backed tests create a throwaway database using `TEST_DATABASE_URL`
(a maintenance-DB URL) and are skipped when it is unset.

Errors use `{"error": {"code": "...", "message": "...", "details": ...}}`.

Note: `uv.lock`/`pip-compile` lock file is not yet generated; dependencies are
pinned with `==` in `pyproject.toml`.

Worked on with Worra ASF.
