# app/api/deps.py
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session_async import get_async_db
from app.models.user import User
from app.schemas.user import TokenPayload


OAUTH_SCOPES = {
    "admin": "Acceso total de administrador.",
    "users:me": "Acceso al perfil del propio usuario.",
    "products:read": "Permiso para leer productos.",
    "products:write": "Permiso para crear, actualizar y eliminar productos.",
    "purchases:read": "Permiso para leer ordenes de compra.",
    "purchases:write": "Permiso para crear y gestionar ordenes de compra.",
    "orders:read": "Permiso para leer ordenes de venta.",
    "orders:write": "Permiso para crear y gestionar ordenes de venta.",
    "cart:read": "Permiso para leer carritos de compra.",
    "cart:write": "Permiso para gestionar carritos de compra.",
    "questions:read": "Permiso para ver preguntas de productos.",
    "questions:write": "Permiso para crear/gestionar preguntas de productos.",
    "notifications:read": "Permiso para leer notificaciones.",
    "notifications:write": "Permiso para gestionar notificaciones.",
    "reports:read": "Permiso para consultar reportes de negocio.",
}


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
    scopes=OAUTH_SCOPES,
)

oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
    scopes=OAUTH_SCOPES,
    auto_error=False,
)


def _decode_token(token: str) -> tuple[TokenPayload, list[str]]:
    payload = decode_access_token(token)
    token_data = TokenPayload(**payload)
    token_scopes: list[str] = payload.get("scopes", []) or []
    return token_data, token_scopes


def decode_token_no_db(token: str) -> TokenPayload:
    token_data, _ = _decode_token(token)
    return token_data

async def _get_user_by_id(db: AsyncSession, user_id: str | None) -> User | None:
    if not user_id:
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_current_user(
    security_scopes: SecurityScopes,
    db: AsyncSession = Depends(get_async_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": f'Bearer scope="{security_scopes.scope_str}"'},
    )

    try:
        token_data, token_scopes = _decode_token(token)
    except JWTError:
        raise cred_exc

    if token_data.sub is None:
        raise cred_exc

    user = await _get_user_by_id(db, token_data.sub)
    if user is None:
        raise cred_exc
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    if security_scopes.scopes:
        if "admin" not in token_scopes or not user.is_superuser:
            for scope in security_scopes.scopes:
                if scope == "admin" or scope not in token_scopes:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not enough permissions",
                        headers={"WWW-Authenticate": f'Bearer scope="{security_scopes.scope_str}"'},
                    )
    return user


async def get_optional_user(
    db: AsyncSession = Depends(get_async_db),
    token: str | None = Depends(oauth2_scheme_optional),
) -> User | None:
    if not token:
        return None

    try:
        token_data, _ = _decode_token(token)
    except JWTError:
        return None

    if token_data.sub is None:
        return None

    user = await _get_user_by_id(db, token_data.sub)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return user


def get_current_active_user(
    current_user: User = Security(get_current_user, scopes=["users:me"])
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if settings.ENFORCE_EMAIL_VERIFICATION and not current_user.email_verified:
        raise HTTPException(status_code=403, detail="Email not verified")
    return current_user


def get_current_admin(
    current_user: User = Security(get_current_user, scopes=["admin"])
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return current_user
