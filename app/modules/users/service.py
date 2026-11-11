from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.modules.authentication.models import RefreshToken
from app.modules.users.models import User


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def activate_user(db: Session, user: User) -> User:
    user.is_active = True
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    return user


def deactivate_user(db: Session, user: User) -> User:
    """Deactivate the account and revoke every live refresh token."""
    user.is_active = False
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.commit()
    return user
