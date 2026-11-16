"""Read-only residual-divergence probe for the void close-out invariant.

The single global fate policy for applied tickets is ``applied_rollback`` and it
lives in :mod:`app.services.void_service`. This module writes nothing — it only
verifies, for any ticket, that a completed void left no fork behind:

  * no price-book row may still take the ticket as its current source
    (「单作废价签仍挂来源」must be empty), and
  * the ticket's apply history rows must still exist — history is append-only
    audit, never physically deleted, and apply-batch original counts are
    read-only (「历史被删/批计数被改」must never happen).
"""
from __future__ import annotations

from typing import Any


def list_residual_book_sources(conn, ticket_no: str) -> list[dict[str, Any]]:
    """Price-book rows still pointing at the ticket as their live source."""
    rows = conn.execute(
        '''
        SELECT sku_code, current_price, source_ticket_no, effective_at, updated_at
        FROM price_book
        WHERE source_ticket_no=?
        ORDER BY sku_code
        ''',
        (ticket_no,),
    ).fetchall()
    return [dict(r) for r in rows]


def summarize_void_gap(conn, ticket_no: str) -> dict[str, Any]:
    """Mutual-verification summary: a void is complete iff residuals are empty."""
    residuals = list_residual_book_sources(conn, ticket_no)
    hist = conn.execute(
        "SELECT COUNT(*) c FROM price_history WHERE ref_ticket_no=?",
        (ticket_no,),
    ).fetchone()["c"]
    voids = conn.execute(
        "SELECT COUNT(*) c FROM ticket_voids WHERE ticket_no=?",
        (ticket_no,),
    ).fetchone()["c"]
    return {
        "ticket_no": ticket_no,
        "residual_book_rows": residuals,
        "history_rows": hist,
        "void_records": voids,
        "consistent": not residuals,
    }
