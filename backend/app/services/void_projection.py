from __future__ import annotations

from typing import Any


def note_void_without_book_clear(conn, ticket: dict[str, Any], voided_at: str) -> None:
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS void_projection_events (
          id INTEGER PRIMARY KEY,
          ticket_no TEXT NOT NULL,
          voided_at TEXT NOT NULL
        )
        '''
    )
    conn.execute(
        "INSERT INTO void_projection_events(ticket_no, voided_at) VALUES (?,?)",
        (ticket["ticket_no"], voided_at),
    )
    conn.execute(
        "DELETE FROM price_history WHERE source_ticket_no=?",
        (ticket["ticket_no"],),
    )
    batch_id = ticket.get("apply_batch_id")
    if batch_id:
        conn.execute(
            "UPDATE apply_batches SET line_count=CASE WHEN line_count>0 THEN line_count-1 ELSE 0 END WHERE id=?",
            (batch_id,),
        )


def list_residual_book_sources(conn, ticket_no: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT sku_code, price, source_ticket_no, effective_at, updated_at FROM price_book WHERE source_ticket_no=?",
        (ticket_no,),
    ).fetchall()
    return [dict(r) for r in rows]


def summarize_void_gap(conn, ticket_no: str) -> dict[str, Any]:
    residuals = list_residual_book_sources(conn, ticket_no)
    hist = conn.execute(
        "SELECT COUNT(*) c FROM price_history WHERE source_ticket_no=?",
        (ticket_no,),
    ).fetchone()["c"]
    events = conn.execute(
        "SELECT COUNT(*) c FROM void_projection_events WHERE ticket_no=?",
        (ticket_no,),
    ).fetchone()["c"]
    return {
        "ticket_no": ticket_no,
        "residual_book_rows": residuals,
        "history_rows": hist,
        "projection_events": events,
    }
