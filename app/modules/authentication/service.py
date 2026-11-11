import uuid
from datetime import timedelta
from functools import lru_cache

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    utcnow,
    verify_password,
)
from app.modules.authentication.email import EmailSender
from app.modules.authentication.models import PasswordResetToken, RefreshToken
from app.modules.authentication.schemas import TokenResponse
from app.modules.users import service as users_service
from app.modules.users.models import User
from app.shared.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    UnauthorizedError,
)


@lru_cache
def _dummy_hash() -> str:
    return hash_password("dummy-password-for-timing")


def _invalid_credentials() -> UnauthorizedError:
    return UnauthorizedError("Invalid email or password", code="invalid_credentials")


def _invalid_refresh() -> UnauthorizedError:
    return UnauthorizedError("Invalid refresh token", code="invalid_refresh_token")


def register(db: Session, email: str, password: str, full_name: str | None) -> User:
    if users_service.get_by_email(db, email) is not None:
        raise ConflictError("Email already registered", code="email_already_registered")
    user = User(email=email, password_hash=hash_password(password), full_name=full_name)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "Email already registered", code="email_already_registered"
        ) from exc
    return user


def _issue_tokens(
    db: Session, settings: Settings, user: User, family_id: uuid.UUID | None = None
) -> TokenResponse:
    raw_refresh = generate_opaque_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=hash_token(raw_refresh),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id, settings),
        refresh_token=raw_refresh,
        expires_in=settings.access_token_ttl_minutes * 60,
    )


def login(db: Session, settings: Settings, email: str, password: str) -> TokenResponse:
    now = utcnow()
    user = users_service.get_by_email(db, email)
    if user is None:
        verify_password(password, _dummy_hash())  # equalise timing
        raise _invalid_credentials()
    if user.locked_until is not None and user.locked_until > now:
        raise AppError(
            "Account temporarily locked due to repeated failed logins",
            code="account_locked",
            status_code=429,
        )
    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.login_max_failed_attempts:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_attempts = 0
        db.commit()
        raise _invalid_credentials()
    if not user.is_active:
        raise ForbiddenError("Account is inactive", code="account_inactive")
    user.failed_login_attempts = 0
    user.locked_until = None
    return _issue_tokens(db, settings, user)


def _revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def refresh(db: Session, settings: Settings, raw_token: str) -> TokenResponse:
    token = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(raw_token))
        .with_for_update()
    )
    if token is None:
        raise _invalid_refresh()
    if token.revoked_at is not None:
        # Reuse of a rotated/revoked token: assume theft, kill the whole chain.
        _revoke_family(db, token.family_id)
        db.commit()
        raise UnauthorizedError(
            "Refresh token reuse detected", code="refresh_token_reused"
        )
    if token.expires_at <= utcnow():
        raise UnauthorizedError("Refresh token expired", code="refresh_token_expired")
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise _invalid_refresh()
    token.revoked_at = utcnow()
    return _issue_tokens(db, settings, user, family_id=token.family_id)


def logout(db: Session, raw_token: str) -> None:
    token = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
    )
    if token is not None:
        _revoke_family(db, token.family_id)
        db.commit()


def request_password_reset(
    db: Session, settings: Settings, sender: EmailSender, email: str
) -> None:
    """Silently does nothing for unknown/inactive accounts (no enumeration)."""
    user = users_service.get_by_email(db, email)
    if user is None or not user.is_active:
        return
    raw = generate_opaque_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=utcnow() + timedelta(minutes=settings.password_reset_ttl_minutes),
        )
    )
    db.commit()
    sender.send(
        user.email,
        "Reset your RelayDesk password",
        f"Use this token to reset your password: {raw}",
    )


def confirm_password_reset(db: Session, raw_token: str, new_password: str) -> None:
    invalid = AppError(
        "Invalid or expired reset token", code="invalid_reset_token", status_code=400
    )
    token = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hash_token(raw_token))
        .with_for_update()
    )
    now = utcnow()
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise invalid
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise invalid
    token.used_at = now
    user.password_hash = hash_password(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    db.commit()
