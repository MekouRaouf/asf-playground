from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.dependencies import AppSettings, DbSession
from app.modules.authentication import service
from app.modules.authentication.email import EmailSender, get_email_sender
from app.modules.authentication.rate_limit import rate_limit
from app.modules.authentication.schemas import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

Sender = Annotated[EmailSender, Depends(get_email_sender)]


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("register"))],
)
def register(body: RegisterRequest, db: DbSession) -> UserRead:
    user = service.register(db, body.email, body.password, body.full_name)
    return UserRead.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("login"))],
)
def login(body: LoginRequest, db: DbSession, settings: AppSettings) -> TokenResponse:
    return service.login(db, settings, body.email, body.password)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("refresh"))],
)
def refresh(
    body: RefreshRequest, db: DbSession, settings: AppSettings
) -> TokenResponse:
    return service.refresh(db, settings, body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, db: DbSession) -> Response:
    service.logout(db, body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password-reset",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("password-reset"))],
)
def password_reset(
    body: PasswordResetRequest, db: DbSession, settings: AppSettings, sender: Sender
) -> dict[str, str]:
    service.request_password_reset(db, settings, sender, body.email)
    return {"status": "accepted"}


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("password-reset-confirm"))],
)
def password_reset_confirm(body: PasswordResetConfirm, db: DbSession) -> Response:
    service.confirm_password_reset(db, body.token, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
