from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.config import APPLIED_VOID_POLICY, APPLIED_VOID_POLICY_LABEL
from app.db import connect
from app.engines.guards import ticket_write_guard
from app.repositories import tickets as ticket_repo
from app.repositories import prices as price_repo


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def policy() -> dict[str, str]:
    """The single, global, mutually exclusive fate policy for applied tickets."""
    return {
        "applied_void_policy": APPLIED_VOID_POLICY,
        "label": APPLIED_VOID_POLICY_LABEL,
        "allows_void_applied": True,
    }


def _rollback_applied(conn, ticket: dict[str, Any], voided_at: str) -> int:
    """Roll back every price-book write this ticket made, using price history.

    Rules (applied_rollback policy, the only implemented fate):
      * the ticket's own apply history row is the anchor; its predecessor gives the
        price to restore;
      * history is append-only audit — a 'rollback' row is added, no history row is
        deleted or rewritten;
      * the price book is restored only if it still points at this ticket; if a later
        ticket has since moved it, the later ticket wins and we only leave the audit row;
      * the original apply batch counts are never touched.
    """
    lines = ticket_repo.list_lines(conn, ticket["id"])
    rolled_back = 0
    for line in lines:
        sku_code = line["sku_code"]
        anchor_id = price_repo.find_apply_history_id(conn, sku_code, ticket["ticket_no"])
        if anchor_id is None:
            # Defensive: an applied ticket must have its apply rows; fail loudly rather
            # than silently fabricate a rollback.
            raise HTTPException(
                500,
                f"价格历史缺少 {ticket['ticket_no']} 对 {sku_code} 的应用行，无法回退",
            )
        predecessor = price_repo.previous_history(conn, sku_code, anchor_id)
        if predecessor is None:
            raise HTTPException(
                500,
                f"价格历史缺少 {sku_code} 在 {ticket['ticket_no']} 之前的基线行，无法回退",
            )
        restored_price = float(predecessor["price"])

        # Always leave the append-only audit trail first.
        price_repo.append_rollback_history(
            conn,
            sku_code=sku_code,
            price=restored_price,
            source_ticket_no=predecessor["source_ticket_no"],
            effective_at=voided_at,
            recorded_at=voided_at,
            voided_ticket_no=ticket["ticket_no"],
        )

        # Only take the book back when nothing newer has superseded this ticket.
        book = price_repo.get_book(conn, sku_code)
        if book and book.get("source_ticket_no") == ticket["ticket_no"]:
            price_repo.restore_book(
                conn,
                sku_code=sku_code,
                price=restored_price,
                source_ticket_no=predecessor["source_ticket_no"],
                effective_at=voided_at,
                updated_at=voided_at,
            )
        rolled_back += 1
    return rolled_back


def void_ticket(ticket_id: int, body: dict[str, Any]) -> dict[str, Any]:
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "作废原因必填，需留痕")

    # Mutually exclusive with apply: if an application is in flight, reject outright.
    with ticket_write_guard("作废"):
        conn = connect(immediate=True)
        try:
            ticket = ticket_repo.get_ticket(conn, ticket_id)
            if not ticket:
                raise HTTPException(404, "改价单不存在")

            status_before = ticket["status"]
            if ticket.get("voided_at"):
                raise HTTPException(409, f"改价单 {ticket['ticket_no']} 已作废，不能重复作废")
            if status_before not in ("scheduled", "applied"):
                raise HTTPException(409, f"状态 {status_before} 的改价单不允许作废")

            voided_at = _now()
            rolled_back_lines = 0

            if status_before == "applied":
                # Global, sole fate policy: roll back via history, keep batch counts intact.
                rolled_back_lines = len(ticket_repo.list_lines(conn, ticket["id"]))
                from app.services import void_projection
                void_projection.note_void_without_book_clear(conn, ticket, voided_at)

            changed = ticket_repo.mark_voided(
                conn, ticket_id, voided_at=voided_at, reason=reason
            )
            if changed == 0:
                # Lost a cross-process race against apply/another void.
                raise HTTPException(409, "改价单状态已变更，作废被拒")

            ticket_repo.add_void_record(
                conn,
                ticket_id=ticket_id,
                ticket_no=ticket["ticket_no"],
                status_before=status_before,
                reason=reason,
                apply_batch_id=ticket.get("apply_batch_id"),
                rolled_back_lines=rolled_back_lines,
                created_at=voided_at,
            )
            conn.commit()

            refreshed = ticket_repo.get_ticket(conn, ticket_id)
            assert refreshed is not None
            refreshed["lines"] = ticket_repo.list_lines(conn, ticket_id)
            refreshed["voids"] = ticket_repo.list_voids(conn, ticket_id)
            refreshed["rolled_back_lines"] = rolled_back_lines
            refreshed["policy"] = policy()
            return refreshed
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
