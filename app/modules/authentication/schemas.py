from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
NewPassword = Annotated[str, Field(min_length=8, max_length=128)]


class RegisterRequest(BaseModel):
    email: Email
    password: NewPassword
    full_name: Annotated[str, Field(max_length=200)] | None = None


class LoginRequest(BaseModel):
    email: Email
    password: Annotated[str, Field(min_length=1, max_length=128)]


class RefreshRequest(BaseModel):
    refresh_token: Annotated[str, Field(min_length=1, max_length=512)]


class PasswordResetRequest(BaseModel):
    email: Email


class PasswordResetConfirm(BaseModel):
    token: Annotated[str, Field(min_length=1, max_length=512)]
    new_password: NewPassword

    @field_validator("token")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int
