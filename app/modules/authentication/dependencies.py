from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.dependencies import AppSettings, DbSession
from app.core.security import decode_access_token
from app.modules.users.models import User
from app.shared.exceptions import ForbiddenError, UnauthorizedError

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    db: DbSession,
    settings: AppSettings,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise UnauthorizedError("Not authenticated", code="not_authenticated")
    user_id = decode_access_token(credentials.credentials, settings)
    user = db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("Invalid access token", code="invalid_token")
    if not user.is_active:
        raise ForbiddenError("Account is inactive", code="account_inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
