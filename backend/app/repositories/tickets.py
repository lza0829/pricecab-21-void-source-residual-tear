from __future__ import annotations

import sqlite3
from typing import Any


def next_ticket_no(conn: sqlite3.Connection) -> str:
    n = conn.execute("SELECT COUNT(*) c FROM price_tickets").fetchone()["c"] + 1
    return f"PT-{n:04d}"


def create_ticket(
    conn: sqlite3.Connection,
    *,
    ticket_no: str,
    title: str,
    effective_at: str,
    note: str | None,
    created_at: str,
) -> int:
    cur = conn.execute(
        '''
        INSERT INTO price_tickets(ticket_no, title, status, effective_at, note, created_at)
        VALUES (?,?,?,?,?,?)
        ''',
        (ticket_no, title, "scheduled", effective_at, note, created_at),
    )
    return int(cur.lastrowid)


def add_line(
    conn: sqlite3.Connection,
    *,
    ticket_id: int,
    sku_code: str,
    old_price: float,
    new_price: float,
) -> int:
    cur = conn.execute(
        '''
        INSERT INTO price_ticket_lines(ticket_id, sku_code, old_price, new_price)
        VALUES (?,?,?,?)
        ''',
        (ticket_id, sku_code, old_price, new_price),
    )
    return int(cur.lastrowid)


def list_tickets(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        '''
        SELECT t.*,
               (SELECT COUNT(*) FROM price_ticket_lines l WHERE l.ticket_id=t.id) AS line_count
        FROM price_tickets t
        ORDER BY t.id DESC
        LIMIT ?
        ''',
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_ticket(conn: sqlite3.Connection, ticket_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM price_tickets WHERE id=?", (ticket_id,)).fetchone()
    return dict(row) if row else None


def list_lines(conn: sqlite3.Connection, ticket_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM price_ticket_lines WHERE ticket_id=? ORDER BY id",
        (ticket_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def due_tickets(conn: sqlite3.Connection, clock_at: str) -> list[dict[str, Any]]:
    # Only live scheduled tickets are ever due; voided tickets are never scanned again.
    rows = conn.execute(
        '''
        SELECT * FROM price_tickets
        WHERE status='scheduled'
          AND voided_at IS NULL
          AND effective_at <= ?
        ORDER BY effective_at, id
        ''',
        (clock_at,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_applied(
    conn: sqlite3.Connection,
    ticket_id: int,
    *,
    applied_at: str,
    batch_id: int,
) -> None:
    # Conditional transition: a ticket that has been voided (or already applied) can never
    # be marked applied by a racing apply. Returns 0 rows -> caller treats as conflict.
    cur = conn.execute(
        '''
        UPDATE price_tickets
        SET status='applied', applied_at=?, apply_batch_id=?
        WHERE id=? AND status='scheduled' AND voided_at IS NULL
        ''',
        (applied_at, batch_id, ticket_id),
    )
    if cur.rowcount == 0:
        raise sqlite3.IntegrityError(
            f"ticket {ticket_id} is not in an applicable state (voided or already applied)"
        )


def mark_voided(
    conn: sqlite3.Connection,
    ticket_id: int,
    *,
    voided_at: str,
    reason: str,
) -> int:
    """Conditional transition scheduled/applied -> voided. Idempotency-safe: returns 0 on re-void."""
    cur = conn.execute(
        '''
        UPDATE price_tickets
        SET status='voided', voided_at=?, void_reason=?, void_count=void_count+1
        WHERE id=? AND voided_at IS NULL AND status IN ('scheduled','applied')
        ''',
        (voided_at, reason, ticket_id),
    )
    return int(cur.rowcount or 0)


def add_void_record(
    conn: sqlite3.Connection,
    *,
    ticket_id: int,
    ticket_no: str,
    status_before: str,
    reason: str,
    apply_batch_id: int | None,
    rolled_back_lines: int,
    created_at: str,
) -> int:
    cur = conn.execute(
        '''
        INSERT INTO ticket_voids(
          ticket_id, ticket_no, status_before, reason, apply_batch_id,
          rolled_back_lines, created_at
        )
        VALUES (?,?,?,?,?,?,?)
        ''',
        (ticket_id, ticket_no, status_before, reason, apply_batch_id, rolled_back_lines, created_at),
    )
    return int(cur.lastrowid)


def list_voids(conn: sqlite3.Connection, ticket_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM ticket_voids WHERE ticket_id=? ORDER BY id",
        (ticket_id,),
    ).fetchall()
    return [dict(r) for r in rows]
