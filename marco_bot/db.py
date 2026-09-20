from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from typing import AsyncIterator

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import Settings
from .constants import DEFAULT_RATE_TIERS, EXPRESS_PAYMENT_MODES
from .models import Base, GlobalStats, PaymentMode, RateTier, RequiredGroup

SessionFactory: async_sessionmaker[AsyncSession] | None = None
Engine: AsyncEngine | None = None


def configure_database(database_url: str, *, null_pool: bool = False) -> None:
    """Configure the global engine/session factory.

    null_pool=True is for serverless runtimes (Vercel): connections are never
    retained, so one engine survives sequential event loops inside a
    long-lived function container.
    """
    global Engine, SessionFactory
    kwargs: dict = {"future": True}
    if null_pool:
        from sqlalchemy.pool import NullPool

        kwargs["poolclass"] = NullPool
    engine = create_async_engine(database_url, **kwargs)
    Engine = engine
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if SessionFactory is None:
        raise RuntimeError("Database is not configured. Call configure_database() first.")
    return SessionFactory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _columns_sync(conn, table: str) -> set[str]:
    dialect = conn.dialect.name
    if dialect == "sqlite":
        rows = conn.exec_driver_sql(f"PRAGMA table_info('{table}')").fetchall()
        return {row[1] for row in rows}
    if "postgres" in dialect:
        rows = conn.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %(t)s",
            {"t": table},
        ).fetchall()
        return {row[0] for row in rows}
    return set()


# Columns added after the original schema; ALTERed in idempotently at startup.
_TABLE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "transactions": [
        ("chain_tx_hash", "TEXT"),
        ("verify_status", "VARCHAR(16)"),
        ("verified_amount", "NUMERIC(24, 8)"),
        ("verify_detail", "TEXT"),
        ("payout_reference", "TEXT"),
    ],
    "users": [
        ("referred_by", "BIGINT"),
        ("lang", "VARCHAR(5)"),
    ],
}


def _ensure_transaction_columns_sync(conn) -> None:
    """Idempotently add newer columns to existing databases.

    create_all only creates missing tables, so deployments with an existing
    schema need these ALTERs. Safe to run on every startup.
    """
    for table, additions in _TABLE_COLUMNS.items():
        existing = _columns_sync(conn, table)
        if not existing:
            continue  # table does not exist yet; create_all handles fresh installs
        for column_name, column_type in additions:
            if column_name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}")


async def init_db(settings: Settings) -> None:
    if Engine is None:
        raise RuntimeError("Database is not configured. Call configure_database() first.")
    async with Engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_transaction_columns_sync)

    async with session_scope() as session:
        stats = await session.get(GlobalStats, 1)
        if not stats:
            session.add(GlobalStats(id=1))

        for mode in EXPRESS_PAYMENT_MODES:
            existing_mode = await session.get(PaymentMode, mode)
            if not existing_mode:
                session.add(PaymentMode(payment_mode=mode, available=True))

        result = await session.execute(select(RateTier.id).limit(1))
        if result.scalar_one_or_none() is None:
            for mode, tiers in DEFAULT_RATE_TIERS.items():
                for min_usd, max_usd, rate in tiers:
                    session.add(
                        RateTier(
                            payment_mode=mode,
                            min_usd=Decimal(str(min_usd)),
                            max_usd=Decimal(str(max_usd)) if max_usd is not None else None,
                            rate_inr=Decimal(str(rate)),
                        )
                    )

        if settings.required_groups:
            await session.execute(delete(RequiredGroup))
            for group in settings.required_groups:
                session.add(
                    RequiredGroup(
                        group_id=group.group_id,
                        invite_link=group.invite_link,
                        label=group.label,
                    )
                )
