from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Category, User
from ..recsys import state
from ..security import (
    current_user,
    end_session,
    hash_password,
    optional_user,
    start_session,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    favorite_category_ids: list[int] = Field(default_factory=list, max_length=12)


class LoginIn(BaseModel):
    username: str
    password: str


class PreferencesIn(BaseModel):
    favorite_category_ids: list[int] = Field(max_length=12)


def user_out(db: Session, user: User) -> dict:
    names = (
        db.scalars(select(Category.name).where(Category.id.in_(user.favorite_category_ids))).all()
        if user.favorite_category_ids
        else []
    )
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "favorite_category_ids": user.favorite_category_ids,
        "favorite_categories": sorted(names),
    }


def _valid_category_ids(db: Session, ids: list[int]) -> list[int]:
    if not ids:
        return []
    return sorted(db.scalars(select(Category.id).where(Category.id.in_(ids))).all())


@router.post("/register", status_code=201)
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    taken = db.scalar(
        select(User).where(
            or_(
                func.lower(User.username) == body.username.lower(),
                func.lower(User.email) == body.email.lower(),
            )
        )
    )
    if taken:
        field = "username" if taken.username.lower() == body.username.lower() else "email"
        raise HTTPException(409, f"That {field} is already registered.")
    user = User(
        name=body.name.strip(),
        username=body.username,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        favorite_category_ids=_valid_category_ids(db, body.favorite_category_ids),
    )
    db.add(user)
    db.commit()
    start_session(response, user)
    return user_out(db, user)


@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.username) == body.username.strip().lower()))
    # Same message either way, so the form does not reveal which usernames exist.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong username or password.")
    start_session(response, user)
    return user_out(db, user)


@router.post("/logout", status_code=204)
def logout(response: Response):
    end_session(response)


@router.get("/me")
def me(user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    return user_out(db, user) if user else None


@router.put("/preferences")
def set_preferences(
    body: PreferencesIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    user = db.merge(user)
    user.favorite_category_ids = _valid_category_ids(db, body.favorite_category_ids)
    db.commit()
    state.mark_changed()
    return user_out(db, user)
