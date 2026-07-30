from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import cfg
from backend.db.connector import get_session
from backend.db.models import User
from backend.login_protection import (
    audit_failure,
    client_ip,
    failure_delay,
    is_rate_limited,
    lock_attempt_buckets,
    normalize_username,
    recent_failure_counts,
)
from backend.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/v1/auth", tags=["auth"])
_DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")


@router.post("/token")
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
):
    username = normalize_username(form.username)
    ip_address = client_ip(request)

    await lock_attempt_buckets(session, username, ip_address)
    username_failures, ip_failures = await recent_failure_counts(
        session, username, ip_address
    )
    if is_rate_limited(username_failures, ip_failures):
        await audit_failure(
            session,
            username=username,
            ip_address=ip_address,
            reason="rate_limited",
        )
        await failure_delay(username_failures)
        raise HTTPException(
            status_code=429,
            detail="Слишком много попыток входа. Повторите позже",
            headers={"Retry-After": str(cfg.auth_rate_limit_window_seconds)},
        )

    user = await session.scalar(select(User).where(User.username == username))
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_is_valid = verify_password(form.password, password_hash)
    if user is None or not user.is_active or not password_is_valid:
        await audit_failure(
            session,
            username=username,
            ip_address=ip_address,
            reason="invalid_credentials",
        )
        await failure_delay(username_failures)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    # The advisory locks are transaction-scoped, so release them before returning.
    # Build the response first: rollback expires ORM attributes and reading user.id
    # afterwards would trigger implicit async I/O (SQLAlchemy MissingGreenlet).
    access_token = create_access_token(user)
    response_username = user.username
    await session.rollback()
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": response_username,
    }


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"id": str(user.id), "username": user.username}
