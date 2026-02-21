from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger, security_alert
from app.core.metrics import record_login_attempt
from app.core.security import (
    create_access_token,
    create_email_verification_token,
    create_refresh_token,
    decode_email_verification_token,
    decode_refresh_token,
)
from app.db.operations import commit_async
from app.db.session_async import get_async_db
from app.models.user import User
from app.schemas.auth import (
    OAuthFrontendConfigResponse,
    OAuthTokenExchangeRequest,
    OAuthUpsertRequest,
    RefreshRequest,
    TokenPair,
    TokenRefresh,
    VerifyEmailRequest,
)
from app.schemas.user import UserRead
from app.services.email_service import send_verification_email
from app.services.oauth_service import (
    OAuthValidationError,
    get_oauth_frontend_providers,
    verify_provider_id_token,
)
from app.services.user_service import (
    authenticate,
    get_by_email,
    mark_email_verified,
    upsert_oauth_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])

auth_logger = get_logger("app.auth")


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else None


def _get_user_scopes(user: User) -> list[str]:
    """Centraliza la lógica de asignación de scopes según el rol del usuario."""
    user_scopes = ["users:me", "reports:read"]
    if user.is_superuser:
        user_scopes.extend(
            ["admin", "products:read", "products:write", "purchases:read", "purchases:write"]
        )
    else:
        user_scopes.extend(["products:read", "purchases:read"])
    return user_scopes


def _build_token_pair(user: User) -> dict[str, object]:
    user_scopes = _get_user_scopes(user)
    access = create_access_token(subject=user.id, extra={"scopes": user_scopes})
    refresh = create_refresh_token(subject=user.id, extra={"scopes": user_scopes})
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": UserRead.model_validate(user),
    }


@router.post("/login", response_model=TokenPair)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_async_db),
):
    user = await authenticate(db, form_data.username, form_data.password)
    if not user:
        record_login_attempt("failure")
        security_alert(
            "Failed login attempt",
            email=form_data.username,
            client_ip=_client_ip(request),
        )
        auth_logger.warning(
            "Failed login attempt",
            extra={"email": form_data.username, "client_ip": _client_ip(request)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password",
        )

    record_login_attempt("success")
    user.last_login_at = datetime.now(timezone.utc)
    db.add(user)
    await commit_async(db)

    auth_logger.info(
        "User authenticated",
        extra={
            "user_id": str(user.id),
            "email": user.email,
            "client_ip": _client_ip(request),
        },
    )

    return _build_token_pair(user)


@router.post("/refresh", response_model=TokenRefresh)
async def refresh_token(payload: RefreshRequest):
    try:
        data = decode_refresh_token(payload.refresh_token)
        user_id = data["sub"]
        token_scopes = data.get("scopes", []) or []
    except (JWTError, KeyError) as exc:
        security_alert("Refresh token validation failed", reason=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from exc

    new_access = create_access_token(subject=user_id, extra={"scopes": token_scopes})
    return {
        "access_token": new_access,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/verify/request", status_code=204)
async def request_email_verification(
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_async_db),
):
    user = await get_by_email(db, payload.email)
    if not user:
        return
    token = create_email_verification_token(user.id)
    verify_url = f"{settings.API_BASE_URL}{settings.API_V1_STR}/auth/verify/confirm?token={token}"
    send_verification_email(user.email, verify_url)


@router.get("/verify/confirm")
async def confirm_email(token: str = Query(...), db: AsyncSession = Depends(get_async_db)):
    try:
        user_id = decode_email_verification_token(token)
    except JWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired token") from exc

    try:
        user_uuid = uuid.UUID(str(user_id))
    except ValueError as exc:  # pragma: no cover - token ya validado en decode
        raise HTTPException(status_code=400, detail="Invalid token payload") from exc

    user = await db.get(User, user_uuid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.email_verified:
        return {"message": "Email already verified"}

    await mark_email_verified(db, user)
    await commit_async(db)
    return {"message": "Email verified successfully"}


@router.post("/oauth/upsert", response_model=TokenPair)
async def oauth_upsert(payload: OAuthUpsertRequest, db: AsyncSession = Depends(get_async_db)):
    from app.schemas.user import UserCreateOAuth  # import local para evitar ciclos

    user_payload = UserCreateOAuth(
        email=payload.email,
        full_name=payload.full_name,
        oauth_provider=payload.provider,
        oauth_sub=payload.sub,
        oauth_picture=payload.picture,
        email_verified_from_provider=bool(payload.email_verified),
    )
    user = await upsert_oauth_user(db, user_payload)

    if settings.ENFORCE_EMAIL_VERIFICATION and not user.email_verified:
        token = create_email_verification_token(user.id)
        verify_url = f"{settings.API_BASE_URL}{settings.API_V1_STR}/auth/verify/confirm?token={token}"
        send_verification_email(user.email, verify_url)
        raise HTTPException(
            status_code=403,
            detail="Email not verified. Verification sent.",
        )

    await commit_async(db)

    return _build_token_pair(user)


@router.get("/oauth/config", response_model=OAuthFrontendConfigResponse)
async def oauth_frontend_config():
    providers = get_oauth_frontend_providers()
    return OAuthFrontendConfigResponse(providers=providers)


@router.post("/oauth/exchange", response_model=TokenPair)
async def oauth_exchange(
    payload: OAuthTokenExchangeRequest,
    db: AsyncSession = Depends(get_async_db),
):
    from app.schemas.user import UserCreateOAuth  # import local para evitar ciclos

    try:
        identity = await verify_provider_id_token(payload.provider, payload.id_token)
    except OAuthValidationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user_payload = UserCreateOAuth(
        email=str(identity["email"]),
        full_name=identity.get("full_name"),
        oauth_provider=str(identity["provider"]),
        oauth_sub=str(identity["sub"]),
        oauth_picture=identity.get("picture"),
        email_verified_from_provider=bool(identity.get("email_verified")),
    )
    user = await upsert_oauth_user(db, user_payload)

    if settings.ENFORCE_EMAIL_VERIFICATION and not user.email_verified:
        token = create_email_verification_token(user.id)
        verify_url = f"{settings.API_BASE_URL}{settings.API_V1_STR}/auth/verify/confirm?token={token}"
        send_verification_email(user.email, verify_url)
        raise HTTPException(
            status_code=403,
            detail="Email not verified. Verification sent.",
        )

    user.last_login_at = datetime.now(timezone.utc)
    db.add(user)
    await commit_async(db)
    return _build_token_pair(user)
