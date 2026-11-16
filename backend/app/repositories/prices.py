from __future__ import annotations

import sqlite3
from typing import Any


def list_book(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        '''
        SELECT b.*, s.title, s.category
        FROM price_book b
        JOIN skus s ON s.sku_code = b.sku_code
        ORDER BY b.sku_code
        '''
    ).fetchall()
    return [dict(r) for r in rows]


def get_book(conn: sqlite3.Connection, sku_code: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM price_book WHERE sku_code=?", (sku_code,)
    ).fetchone()
    return dict(row) if row else None


def _insert_history(
    conn: sqlite3.Connection,
    *,
    sku_code: str,
    price: float,
    source_ticket_no: str | None,
    effective_at: str,
    recorded_at: str,
    entry_type: str,
    ref_ticket_no: str | None,
) -> None:
    conn.execute(
        '''
        INSERT INTO price_history(
          sku_code, price, source_ticket_no, effective_at, recorded_at, entry_type, ref_ticket_no
        )
        VALUES (?,?,?,?,?,?,?)
        ''',
        (sku_code, price, source_ticket_no, effective_at, recorded_at, entry_type, ref_ticket_no),
    )


def upsert_book(
    conn: sqlite3.Connection,
    *,
    sku_code: str,
    price: float,
    ticket_no: str,
    effective_at: str,
    updated_at: str,
) -> None:
    conn.execute(
        '''
        INSERT INTO price_book(sku_code, current_price, source_ticket_no, effective_at, updated_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(sku_code) DO UPDATE SET
          current_price=excluded.current_price,
          source_ticket_no=excluded.source_ticket_no,
          effective_at=excluded.effective_at,
          updated_at=excluded.updated_at
        ''',
        (sku_code, price, ticket_no, effective_at, updated_at),
    )
    _insert_history(
        conn,
        sku_code=sku_code,
        price=price,
        source_ticket_no=ticket_no,
        effective_at=effective_at,
        recorded_at=updated_at,
        entry_type="apply",
        ref_ticket_no=ticket_no,
    )


def find_apply_history_id(conn: sqlite3.Connection, sku_code: str, ticket_no: str) -> int | None:
    """The history row this ticket's application wrote for the SKU (audit anchor for rollback)."""
    row = conn.execute(
        '''
        SELECT id FROM price_history
        WHERE sku_code=? AND ref_ticket_no=? AND entry_type='apply'
        ORDER BY id ASC
        LIMIT 1
        ''',
        (sku_code, ticket_no),
    ).fetchone()
    return int(row["id"]) if row else None


def previous_history(conn: sqlite3.Connection, sku_code: str, before_id: int) -> dict[str, Any] | None:
    """Latest history row preceding the ticket's own apply row — the price to roll back to."""
    row = conn.execute(
        '''
        SELECT * FROM price_history
        WHERE sku_code=? AND id < ?
        ORDER BY id DESC
        LIMIT 1
        ''',
        (sku_code, before_id),
    ).fetchone()
    return dict(row) if row else None


def append_rollback_history(
    conn: sqlite3.Connection,
    *,
    sku_code: str,
    price: float,
    source_ticket_no: str | None,
    effective_at: str,
    recorded_at: str,
    voided_ticket_no: str,
) -> None:
    """Append-only audit row for a void. History rows are never deleted or overwritten."""
    _insert_history(
        conn,
        sku_code=sku_code,
        price=price,
        source_ticket_no=source_ticket_no,
        effective_at=effective_at,
        recorded_at=recorded_at,
        entry_type="rollback",
        ref_ticket_no=voided_ticket_no,
    )


def restore_book(
    conn: sqlite3.Connection,
    *,
    sku_code: str,
    price: float,
    source_ticket_no: str | None,
    effective_at: str,
    updated_at: str,
) -> None:
    """Point the price book back at the predecessor price."""
    conn.execute(
        '''
        UPDATE price_book
        SET current_price=?, source_ticket_no=?, effective_at=?, updated_at=?
        WHERE sku_code=?
        ''',
        (price, source_ticket_no, effective_at, updated_at, sku_code),
    )


def list_history(conn: sqlite3.Connection, sku_code: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if sku_code:
        rows = conn.execute(
            "SELECT * FROM price_history WHERE sku_code=? ORDER BY id DESC LIMIT ?",
            (sku_code, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM price_history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def price_at(conn: sqlite3.Connection, sku_code: str, at: str) -> float | None:
    row = conn.execute(
        '''
        SELECT price FROM price_history
        WHERE sku_code=? AND effective_at <= ?
        ORDER BY effective_at DESC, id DESC
        LIMIT 1
        ''',
        (sku_code, at),
    ).fetchone()
    return float(row["price"]) if row else None


def list_book_by_source(conn, ticket_no: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM price_book WHERE source_ticket_no=? ORDER BY sku_code",
        (ticket_no,),
    ).fetchall()
    return [dict(r) for r in rows]

