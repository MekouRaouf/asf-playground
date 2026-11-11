from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("psycopg")
pytest.importorskip("argon2")
jwt = pytest.importorskip("jwt")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.security import (  # noqa: E402
    create_access_token,
    decode_access_token,
    hash_password,
    hash_token,
    utcnow,
    verify_password,
)
from app.main import create_app  # noqa: E402
from app.modules.authentication.email import (  # noqa: E402
    InMemoryEmailSender,
    get_email_sender,
)
from app.modules.authentication.models import (  # noqa: E402
    PasswordResetToken,
    RefreshToken,
)
from app.modules.authentication.rate_limit import rate_limiter  # noqa: E402
from app.modules.users.models import User  # noqa: E402
from app.shared.exceptions import UnauthorizedError  # noqa: E402

PASSWORD = "correct horse battery"
PREFIX = "/api/v1"


@pytest.fixture
def sender() -> InMemoryEmailSender:
    return InMemoryEmailSender()


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def client(
    session_factory: sessionmaker[Session], sender: InMemoryEmailSender
) -> Iterator[TestClient]:
    rate_limiter.reset()
    app = create_app()

    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield TestClient(app)
    rate_limiter.reset()


def settings() -> Settings:
    return get_settings()


def register(client: TestClient, email: str = "a@example.com") -> Any:
    return client.post(
        f"{PREFIX}/auth/register", json={"email": email, "password": PASSWORD}
    )


def login(client: TestClient, email: str = "a@example.com", pw: str = PASSWORD) -> Any:
    return client.post(f"{PREFIX}/auth/login", json={"email": email, "password": pw})


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---- unit: security ----------------------------------------------------------


def test_password_hashed_with_argon2_and_verifies() -> None:
    hashed = hash_password(PASSWORD)
    assert PASSWORD not in hashed
    assert hashed.startswith("$argon2")
    assert verify_password(PASSWORD, hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password(PASSWORD, "not-a-hash")


def test_access_token_roundtrip() -> None:
    user = User(email="x@example.com", password_hash="x")
    user.id = __import__("uuid").uuid4()
    token = create_access_token(user.id, settings())
    assert decode_access_token(token, settings()) == user.id


def test_expired_access_token_rejected() -> None:
    import uuid

    old = utcnow() - timedelta(hours=2)
    token = create_access_token(uuid.uuid4(), settings(), now=old)
    with pytest.raises(UnauthorizedError) as exc:
        decode_access_token(token, settings())
    assert exc.value.code == "token_expired"


def test_wrong_algorithm_and_unsigned_tokens_rejected() -> None:
    import uuid

    now = utcnow()
    payload = {
        "sub": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": "1",
        "iss": settings().jwt_issuer,
        "typ": "access",
    }
    key = settings().secret_key.get_secret_value() * 4
    hs512 = jwt.encode(payload, key, algorithm="HS512")
    unsigned = jwt.encode(payload, None, algorithm="none")
    for bad in (hs512, unsigned, "garbage"):
        with pytest.raises(UnauthorizedError) as exc:
            decode_access_token(bad, settings())
        assert exc.value.code == "invalid_token"


def test_token_missing_required_claim_rejected() -> None:
    now = utcnow()
    token = jwt.encode(
        {"sub": "abc", "exp": now + timedelta(minutes=5)},
        settings().secret_key.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(UnauthorizedError):
        decode_access_token(token, settings())


# ---- integration: register / login ------------------------------------------


def test_register_stores_hashed_password(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    response = register(client, "  A@Example.com ")
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "a@example.com"
    assert "password" not in body and "password_hash" not in body
    with session_factory() as db:
        user = db.scalar(select(User))
        assert user is not None
        assert user.password_hash != PASSWORD
        assert user.password_hash.startswith("$argon2")


def test_register_duplicate_conflict_and_validation(client: TestClient) -> None:
    assert register(client).status_code == 201
    dup = register(client)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "email_already_registered"
    short = client.post(
        f"{PREFIX}/auth/register", json={"email": "b@example.com", "password": "x"}
    )
    assert short.status_code == 422
    bad = client.post(
        f"{PREFIX}/auth/register", json={"email": "nope", "password": PASSWORD}
    )
    assert bad.status_code == 422


def test_login_success_and_me(client: TestClient) -> None:
    register(client)
    response = login(client)
    assert response.status_code == 200
    tokens = response.json()
    assert tokens["token_type"] == "bearer"
    me = client.get(f"{PREFIX}/users/me", headers=auth(tokens["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"


def test_login_invalid_credentials(client: TestClient) -> None:
    register(client)
    wrong = login(client, pw="wrong-password")
    unknown = login(client, email="nobody@example.com")
    for response in (wrong, unknown):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"
    assert wrong.json() == unknown.json()


def test_me_requires_valid_token(client: TestClient) -> None:
    assert client.get(f"{PREFIX}/users/me").status_code == 401
    bad = client.get(f"{PREFIX}/users/me", headers=auth("garbage"))
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_token"


def test_expired_access_token_rejected_by_api(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    register(client)
    with session_factory() as db:
        user = db.scalar(select(User))
        assert user is not None
        token = create_access_token(
            user.id, settings(), now=utcnow() - timedelta(hours=1)
        )
    response = client.get(f"{PREFIX}/users/me", headers=auth(token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


# ---- integration: inactive users --------------------------------------------


def test_inactive_user_cannot_login(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    register(client)
    with session_factory() as db:
        user = db.scalar(select(User))
        assert user is not None
        user.is_active = False
        db.commit()
    response = login(client)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_inactive"


def test_deactivation_revokes_tokens_and_blocks_access(
    client: TestClient,
) -> None:
    register(client)
    tokens = login(client).json()
    headers = auth(tokens["access_token"])
    assert client.post(f"{PREFIX}/users/me/deactivate", headers=headers).status_code == 204
    assert client.get(f"{PREFIX}/users/me", headers=headers).status_code == 403
    refreshed = client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 401
    assert login(client).status_code == 403


# ---- integration: refresh rotation / logout ---------------------------------


def test_refresh_rotates_and_stores_hashed(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    register(client)
    first = login(client).json()
    response = client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert response.status_code == 200
    second = response.json()
    assert second["refresh_token"] != first["refresh_token"]
    with session_factory() as db:
        hashes = set(db.scalars(select(RefreshToken.token_hash)))
    assert hash_token(first["refresh_token"]) in hashes
    assert first["refresh_token"] not in hashes
    assert second["refresh_token"] not in hashes


def test_reused_refresh_token_rejected_and_family_revoked(client: TestClient) -> None:
    register(client)
    first = login(client).json()
    second = client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": first["refresh_token"]}
    ).json()
    reuse = client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "refresh_token_reused"
    # the descendant token is revoked as well
    descendant = client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert descendant.status_code == 401


def test_unknown_and_expired_refresh_tokens_rejected(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    register(client)
    tokens = login(client).json()
    unknown = client.post(f"{PREFIX}/auth/refresh", json={"refresh_token": "nope"})
    assert unknown.status_code == 401
    with session_factory() as db:
        row = db.scalar(select(RefreshToken))
        assert row is not None
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    expired = client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "refresh_token_expired"


def test_logout_revokes_refresh_token(client: TestClient) -> None:
    register(client)
    tokens = login(client).json()
    out = client.post(
        f"{PREFIX}/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert out.status_code == 204
    after = client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert after.status_code == 401
    # logout is idempotent and does not leak token validity
    again = client.post(f"{PREFIX}/auth/logout", json={"refresh_token": "nope"})
    assert again.status_code == 204


# ---- integration: password reset --------------------------------------------


def _reset_token(sender: InMemoryEmailSender) -> str:
    return sender.outbox[-1][2].rsplit(": ", 1)[1]


def test_password_reset_flow(
    client: TestClient,
    sender: InMemoryEmailSender,
    session_factory: sessionmaker[Session],
) -> None:
    register(client)
    old_tokens = login(client).json()
    response = client.post(
        f"{PREFIX}/auth/password-reset", json={"email": "a@example.com"}
    )
    assert response.status_code == 202
    assert len(sender.outbox) == 1
    raw = _reset_token(sender)
    with session_factory() as db:
        stored = db.scalar(select(PasswordResetToken.token_hash))
    assert stored == hash_token(raw) and stored != raw

    confirm = client.post(
        f"{PREFIX}/auth/password-reset/confirm",
        json={"token": raw, "new_password": "brand new password"},
    )
    assert confirm.status_code == 204
    assert login(client).status_code == 401
    assert login(client, pw="brand new password").status_code == 200
    # existing sessions are revoked
    stale = client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": old_tokens["refresh_token"]}
    )
    assert stale.status_code == 401

    # single use
    again = client.post(
        f"{PREFIX}/auth/password-reset/confirm",
        json={"token": raw, "new_password": "another password"},
    )
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "invalid_reset_token"


def test_password_reset_unknown_email_is_silent(
    client: TestClient, sender: InMemoryEmailSender
) -> None:
    response = client.post(
        f"{PREFIX}/auth/password-reset", json={"email": "ghost@example.com"}
    )
    assert response.status_code == 202
    assert sender.outbox == []


def test_password_reset_expired_token_rejected(
    client: TestClient,
    sender: InMemoryEmailSender,
    session_factory: sessionmaker[Session],
) -> None:
    register(client)
    client.post(f"{PREFIX}/auth/password-reset", json={"email": "a@example.com"})
    with session_factory() as db:
        row = db.scalar(select(PasswordResetToken))
        assert row is not None
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    response = client.post(
        f"{PREFIX}/auth/password-reset/confirm",
        json={"token": _reset_token(sender), "new_password": "brand new password"},
    )
    assert response.status_code == 400


# ---- brute force / rate limiting --------------------------------------------


def test_lockout_after_repeated_failures(client: TestClient) -> None:
    register(client)
    limit = settings().login_max_failed_attempts
    for _ in range(limit):
        assert login(client, pw="wrong-password").status_code == 401
    locked = login(client)  # correct password, still refused
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "account_locked"


def test_lockout_expires_and_success_resets_counter(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    register(client)
    limit = settings().login_max_failed_attempts
    for _ in range(limit - 1):
        login(client, pw="wrong-password")
    assert login(client).status_code == 200  # counter reset by success
    for _ in range(limit):
        login(client, pw="wrong-password")
    assert login(client).status_code == 429
    with session_factory() as db:
        user = db.scalar(select(User))
        assert user is not None
        user.locked_until = utcnow() - timedelta(seconds=1)
        db.commit()
    assert login(client).status_code == 200


def test_rate_limit_on_sensitive_endpoints(client: TestClient) -> None:
    client.app.dependency_overrides[get_settings] = lambda: Settings(  # type: ignore[attr-defined]
        rate_limit_per_minute=3
    )
    statuses = [login(client, email="nobody@example.com").status_code for _ in range(5)]
    assert statuses[:3] == [401, 401, 401]
    assert statuses[3:] == [429, 429]
    limited = login(client, email="nobody@example.com")
    assert limited.json()["error"]["code"] == "rate_limited"
    # scopes are independent
    reset = client.post(f"{PREFIX}/auth/password-reset", json={"email": "a@example.com"})
    assert reset.status_code == 202
