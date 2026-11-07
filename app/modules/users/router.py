from fastapi import APIRouter, Response, status

from app.core.dependencies import DbSession
from app.modules.authentication.dependencies import CurrentUser
from app.modules.users import service
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
def read_me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.post("/me/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_me(user: CurrentUser, db: DbSession) -> Response:
    service.deactivate_user(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
