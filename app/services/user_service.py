from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.db.operations import flush_async, refresh_async
from app.models.user import User
from app.schemas.user import UserCreate, UserCreateOAuth, UserUpdate


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email).limit(1)
    result = await db.execute(stmt)
    return result.scalars().first()


async def create_user(db: AsyncSession, data: UserCreate) -> User:
    user = User(
        email=data.email,
        full_name=data.full_name,
        hashed_password=get_password_hash(data.password),
        address_line1=data.address_line1,
        address_line2=data.address_line2,
        city=data.city,
        state=data.state,
        postal_code=data.postal_code,
        country=data.country,
        phone=data.phone,
        birthdate=data.birthdate,
        avatar_url=str(data.avatar_url) if data.avatar_url else None,
        email_verified=False,
    )
    db.add(user)
    #en este espacio es donde tenemos el umbral de gestion de errores
    await flush_async(db, user)
    await refresh_async(db, user)
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_by_email(db, email)
    if not user or not user.hashed_password:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def get_by_oauth(db: AsyncSession, provider: str, sub: str) -> User | None:
    stmt = (
        select(User)
        .where(User.oauth_provider == provider)
        .where(User.oauth_sub == sub)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def upsert_oauth_user(db: AsyncSession, data: UserCreateOAuth) -> User:
    user = await get_by_oauth(db, data.oauth_provider, data.oauth_sub)
    if user:
        if data.full_name and user.full_name != data.full_name:
            user.full_name = data.full_name
        if data.oauth_picture:
            user.oauth_picture = str(data.oauth_picture)
        if not user.email_verified and data.email_verified_from_provider:
            user.email_verified = True
    else:
        user = await get_by_email(db, data.email)
        if user:
            user.oauth_provider = data.oauth_provider
            user.oauth_sub = data.oauth_sub
            if data.oauth_picture:
                user.oauth_picture = str(data.oauth_picture)
            if not user.email_verified and data.email_verified_from_provider:
                user.email_verified = True
        else:
            user = User(
                email=data.email,
                full_name=data.full_name,
                oauth_provider=data.oauth_provider,
                oauth_sub=data.oauth_sub,
                oauth_picture=str(data.oauth_picture) if data.oauth_picture else None,
                email_verified=bool(data.email_verified_from_provider),
            )
            db.add(user)
    await flush_async(db, user)
    await refresh_async(db, user)
    return user


async def mark_email_verified(db: AsyncSession, user: User) -> User:
    user.email_verified = True
    db.add(user)
    await flush_async(db, user)
    await refresh_async(db, user)
    return user


async def update_user(db: AsyncSession, user: User, changes: UserUpdate) -> User:
    data = changes.model_dump(exclude_unset=True)
    if "avatar_url" in data and data["avatar_url"] is not None:
        data["avatar_url"] = str(data["avatar_url"])
    for field, value in data.items():
        setattr(user, field, value)
    db.add(user)
    await flush_async(db, user)
    await refresh_async(db, user)
    return user
