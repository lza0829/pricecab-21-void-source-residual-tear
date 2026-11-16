from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.db import connect
from app.engines.guards import ticket_write_guard
from app.repositories import settings as settings_repo
from app.repositories import tickets as ticket_repo
from app.repositories import prices as price_repo
from app.repositories import batches as batch_repo


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_clock() -> dict[str, Any]:
    conn = connect()
    try:
        return {
            "business_clock": settings_repo.get(conn, "business_clock"),
            "clock_label": settings_repo.get(conn, "clock_label"),
        }
    finally:
        conn.close()


def set_clock(clock_at: str) -> dict[str, Any]:
    clock_at = (clock_at or "").strip()
    if not clock_at:
        raise HTTPException(400, "业务钟不能为空")
    conn = connect(immediate=True)
    try:
        settings_repo.set_value(conn, "business_clock", clock_at)
        conn.commit()
        return get_clock()
    finally:
        conn.close()


def list_batches() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return batch_repo.list_batches(conn)
    finally:
        conn.close()


def apply_due() -> dict[str, Any]:
    """Apply all scheduled tickets whose effective_at <= business clock.

    Mutually exclusive with voiding: if a void is in flight this is rejected with 409,
    and a ticket voided inside another transaction can never be marked applied here.
    """
    with ticket_write_guard("应用"):
        conn = connect(immediate=True)
        try:
            clock = settings_repo.get(conn, "business_clock")
            if not clock:
                raise HTTPException(400, "业务钟未设置")
            due = ticket_repo.due_tickets(conn, clock)
            if not due:
                conn.commit()
                return {
                    "applied": False,
                    "message": "当前业务钟下没有到期改价单",
                    "business_clock": clock,
                    "ticket_count": 0,
                    "line_count": 0,
                }

            batch_no = batch_repo.next_batch_no(conn)
            created = _now()
            line_total = 0
            applied_tickets: list[str] = []
            # create batch first with zeros, update after
            batch_id = batch_repo.create_batch(
                conn,
                batch_no=batch_no,
                clock_at=clock,
                ticket_count=0,
                line_count=0,
                status="running",
                created_at=created,
            )

            for t in due:
                # Re-read under the write lock/transaction: a ticket voided after the scan
                # must not produce another successful application.
                fresh = ticket_repo.get_ticket(conn, t["id"])
                if not fresh or fresh["status"] != "scheduled" or fresh.get("voided_at"):
                    raise HTTPException(
                        409,
                        f"改价单 {t['ticket_no']} 在应用过程中已不可应用（可能已作废），本次应用拒绝",
                    )
                lines = ticket_repo.list_lines(conn, t["id"])
                for line in lines:
                    price_repo.upsert_book(
                        conn,
                        sku_code=line["sku_code"],
                        price=float(line["new_price"]),
                        ticket_no=t["ticket_no"],
                        effective_at=t["effective_at"],
                        updated_at=created,
                    )
                    line_total += 1
                try:
                    ticket_repo.mark_applied(conn, t["id"], applied_at=created, batch_id=batch_id)
                except sqlite3.IntegrityError as exc:  # racing void won the conditional update
                    raise HTTPException(409, f"应用与作废冲突，应用被拒：{exc}") from exc
                applied_tickets.append(t["ticket_no"])

            conn.execute(
                "UPDATE apply_batches SET ticket_count=?, line_count=?, status=? WHERE id=?",
                (len(due), line_total, "done", batch_id),
            )
            conn.commit()
            return {
                "applied": True,
                "batch_no": batch_no,
                "business_clock": clock,
                "ticket_count": len(due),
                "line_count": line_total,
                "tickets": applied_tickets,
            }
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
