from __future__ import annotations

from typing import Any

from app.db import connect
from app.repositories import sales as sales_repo
from app.repositories import prices as price_repo


def reconcile_sales() -> dict[str, Any]:
    """Compare each sale's unit_price with the price book value effective at sold_at."""
    conn = connect()
    try:
        sales = sales_repo.list_sales(conn)
        rows = []
        match = 0
        mismatch = 0
        missing = 0
        for s in sales:
            expected = price_repo.price_at(conn, s["sku_code"], s["sold_at"])
            sold = float(s["unit_price"])
            if expected is None:
                status = "missing_price"
                missing += 1
                delta = None
            elif abs(expected - sold) < 1e-9:
                status = "match"
                match += 1
                delta = 0.0
            else:
                status = "mismatch"
                mismatch += 1
                delta = round(sold - expected, 4)
            rows.append(
                {
                    **s,
                    "expected_price": expected,
                    "delta": delta,
                    "status": status,
                }
            )
        return {
            "sale_count": len(sales),
            "match_count": match,
            "mismatch_count": mismatch,
            "missing_count": missing,
            "rows": rows,
        }
    finally:
        conn.close()


def list_price_book() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return price_repo.list_book(conn)
    finally:
        conn.close()


def list_history(sku_code: str | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return price_repo.list_history(conn, sku_code=sku_code)
    finally:
        conn.close()
