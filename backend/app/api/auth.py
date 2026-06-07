from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import TokenResponse, UserLogin, UserRead, UserRegister
from app.services import auth as auth_service
from app.services import users as user_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(registration: UserRegister, db: DatabaseSession) -> UserRead:
    try:
        return UserRead.model_validate(user_service.register_user(db, registration))
    except user_service.DuplicateUserEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        ) from exc


@router.post("/login", response_model=TokenResponse)
def login(credentials: UserLogin, db: DatabaseSession) -> TokenResponse:
    try:
        return auth_service.login(db, credentials)
    except auth_service.InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        ) from exc


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)
