"""Password hashing (Argon2id), strict JWT handling and opaque-token helpers."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings
from app.shared.exceptions import UnauthorizedError

ACCESS_TOKEN_TYPE = "access"  # noqa: S105
_REQUIRED_CLAIMS = ["exp", "iat", "sub", "jti", "iss", "typ"]

_hasher = PasswordHasher()


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(
    subject: uuid.UUID, settings: Settings, *, now: datetime | None = None
) -> str:
    issued = now or utcnow()
    payload = {
        "sub": str(subject),
        "iat": issued,
        "exp": issued + timedelta(minutes=settings.access_token_ttl_minutes),
        "jti": uuid.uuid4().hex,
        "iss": settings.jwt_issuer,
        "typ": ACCESS_TOKEN_TYPE,
    }
    return jwt.encode(
        payload, settings.secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    """Validate signature, pinned algorithm, expiry and claims; return the user id."""
    try:
        claims = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": _REQUIRED_CLAIMS},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Access token has expired", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid access token", code="invalid_token") from exc
    if claims["typ"] != ACCESS_TOKEN_TYPE:
        raise UnauthorizedError("Invalid access token", code="invalid_token")
    try:
        return uuid.UUID(claims["sub"])
    except (ValueError, TypeError) as exc:
        raise UnauthorizedError("Invalid access token", code="invalid_token") from exc


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Deterministic digest for high-entropy opaque tokens (stored instead of raw)."""
    return hashlib.sha256(token.encode()).hexdigest()
