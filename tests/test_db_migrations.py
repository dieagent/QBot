"""Regression tests for the idempotent column migration (db.py).

The live failure: the postgres branch bound information_schema with
pyformat %(t)s, which asyncpg rejects — the webhook 500'd at boot.
"""
from __future__ import annotations

from sqlalchemy import text

from marco_bot.db import _TABLE_COLUMNS, _columns_sync


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeDialect:
    name = "postgresql"


class _FakePostgresConn:
    """Mimics the run_sync connection facade for the postgres branch."""

    dialect = _FakeDialect()
    executed: list[tuple[str, dict]] = []

    def __init__(self, rows):
        self._rows = rows
        self.calls: list[tuple[str, dict]] = []

    def execute(self, clause, params=None):
        sql = str(clause)
        self.calls.append((sql, dict(params or {})))
        return _FakeResult(self._rows)


def test_postgres_branch_uses_sqlalchemy_text_bind() -> None:
    conn = _FakePostgresConn([("user_id",), ("referred_by",), ("lang",)])
    columns = _columns_sync(conn, "users")
    assert columns == {"user_id", "referred_by", "lang"}
    (sql, params), = conn.calls
    assert "information_schema.columns" in sql
    # bound as an SQLAlchemy parameter, never driver pyformat
    assert "%(" not in sql
    assert params == {"t": "users"}


def test_untouched_columns_set_is_plain_data() -> None:
    normalized = {table: {name for name, _ in cols} for table, cols in _TABLE_COLUMNS.items()}
    assert "payout_reference" in normalized["transactions"]
    assert "referred_by" in normalized["users"]
    assert "lang" in normalized["users"]
    # legacy columns from the on-chain upgrade must still be migrated too
    assert {"chain_tx_hash", "verify_status", "verified_amount", "verify_detail"} <= normalized["transactions"]


def test_text_clause_styles() -> None:
    # what the postgres branch now emits; documenting the contract
    clause = text("SELECT column_name FROM information_schema.columns WHERE table_name = :t")
    assert "%" not in str(clause)
