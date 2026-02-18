"""Utilities to bootstrap initial application data."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.db.session_async import AsyncSessionLocal
from app.models.user import User
from app.schemas.user import UserCreate
from app.services import user_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _advisory_lock(session: AsyncSession):
    """Prevent concurrent admin initialization when running on PostgreSQL."""
    dialect = session.bind.dialect.name if session.bind else "unknown"
    lock_key = 987654321
    got_lock = False
    try:
        if dialect == "postgresql":
            res = await session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key})
            got_lock = bool(res.scalar())
            if not got_lock:
                logger.info("Another worker is already initializing the admin; skipping this pass.")
                yield False
                return
        yield True
    finally:
        if got_lock:
            await session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key})


async def create_initial_admin_user() -> None:
    """Ensure the initial admin user matches the credentials configured in the environment."""
    if not settings.INITIAL_ADMIN_EMAIL or not settings.INITIAL_ADMIN_PASSWORD:
        logger.info("Skipping admin init: INITIAL_ADMIN_EMAIL or INITIAL_ADMIN_PASSWORD is missing.")
        return

    admin_email = str(settings.INITIAL_ADMIN_EMAIL)
    admin_password = settings.INITIAL_ADMIN_PASSWORD
    logger.info("Initial admin sync: starting verification.", extra={"email": admin_email})

    async with AsyncSessionLocal() as session:
        async with _advisory_lock(session) as proceed:
            if proceed is False:
                return

            stmt = select(func.count()).select_from(User).where(User.is_superuser.is_(True))
            superuser_count = (await session.execute(stmt)).scalar() or 0

            existing = await user_service.get_by_email(session, admin_email)
            if existing:
                updated = False
                if not existing.is_superuser:
                    existing.is_superuser = True
                    updated = True
                if not existing.email_verified:
                    existing.email_verified = True
                    updated = True

                needs_reset = (
                    bool(admin_password)
                    and (
                        not existing.hashed_password
                        or not verify_password(admin_password, existing.hashed_password)
                    )
                )
                if needs_reset:
                    existing.hashed_password = get_password_hash(admin_password)
                    updated = True

                if updated:
                    session.add(existing)
                    await session.commit()
                    await session.refresh(existing)
                    logger.info(
                        "Initial admin synchronized with environment credentials.",
                        extra={"user_id": str(existing.id), "email": existing.email},
                    )
                else:
                    logger.info(
                        "Initial admin already matches configured credentials.",
                        extra={"user_id": str(existing.id), "email": existing.email},
                    )
                return

            if superuser_count > 0:
                logger.warning(
                    "Existing superusers detected; creating the configured initial admin anyway.",
                    extra={"email": admin_email},
                )

            user_in = UserCreate(
                email=admin_email,
                password=admin_password,
                full_name="Initial Admin",
            )

            user = await user_service.create_user(session, user_in)
            user.is_superuser = True
            user.email_verified = True
            session.add(user)
            await session.commit()
            await session.refresh(user)

            logger.info(
                "Initial admin created successfully.",
                extra={"user_id": str(user.id), "email": user.email},
            )
