import os
import uuid
from collections.abc import Iterator

import pytest

os.environ.setdefault("SECRET_KEY", "test-only-secret")
# Deliberately unreachable by default so readiness tests never need a real DB.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://nobody:nopass@127.0.0.1:1/nodb"
)


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    """Create an isolated, throwaway PostgreSQL database for the session.

    Requires TEST_DATABASE_URL pointing at a server/maintenance DB; skipped otherwise.
    """
    admin_url = os.environ.get("TEST_DATABASE_URL")
    if not admin_url:
        pytest.skip("TEST_DATABASE_URL not set")
    sa = pytest.importorskip("sqlalchemy")
    from sqlalchemy.engine import make_url

    from app.core.database import normalize_url

    base = make_url(normalize_url(admin_url))
    name = f"relaydesk_test_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    except sa.exc.OperationalError:
        admin.dispose()
        pytest.skip("PostgreSQL not reachable")
    try:
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def db_session(test_database_url: str) -> Iterator[object]:
    from sqlalchemy.orm import Session

    from app.core.database import build_engine

    engine = build_engine(test_database_url)
    with Session(engine) as session:
        yield session
    engine.dispose()
