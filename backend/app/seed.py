from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.db import connect


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def init_schema(conn) -> None:
    conn.executescript(
        '''
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS skus (
          id INTEGER PRIMARY KEY,
          sku_code TEXT NOT NULL UNIQUE,
          title TEXT NOT NULL,
          category TEXT NOT NULL,
          list_price REAL NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS price_tickets (
          id INTEGER PRIMARY KEY,
          ticket_no TEXT NOT NULL UNIQUE,
          title TEXT NOT NULL,
          status TEXT NOT NULL,
          effective_at TEXT NOT NULL,
          note TEXT,
          created_at TEXT NOT NULL,
          applied_at TEXT,
          apply_batch_id INTEGER,
          voided_at TEXT,
          void_reason TEXT,
          void_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS price_ticket_lines (
          id INTEGER PRIMARY KEY,
          ticket_id INTEGER NOT NULL REFERENCES price_tickets(id) ON DELETE CASCADE,
          sku_code TEXT NOT NULL,
          old_price REAL NOT NULL,
          new_price REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS apply_batches (
          id INTEGER PRIMARY KEY,
          batch_no TEXT NOT NULL UNIQUE,
          clock_at TEXT NOT NULL,
          ticket_count INTEGER NOT NULL,
          line_count INTEGER NOT NULL,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_book (
          sku_code TEXT PRIMARY KEY,
          current_price REAL NOT NULL,
          source_ticket_no TEXT,
          effective_at TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_history (
          id INTEGER PRIMARY KEY,
          sku_code TEXT NOT NULL,
          price REAL NOT NULL,
          source_ticket_no TEXT,
          effective_at TEXT NOT NULL,
          recorded_at TEXT NOT NULL,
          entry_type TEXT NOT NULL DEFAULT 'apply',
          ref_ticket_no TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_price_history_sku ON price_history(sku_code, id);
        CREATE TABLE IF NOT EXISTS ticket_voids (
          id INTEGER PRIMARY KEY,
          ticket_id INTEGER NOT NULL,
          ticket_no TEXT NOT NULL,
          status_before TEXT NOT NULL,
          reason TEXT NOT NULL,
          apply_batch_id INTEGER,
          rolled_back_lines INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ticket_voids_ticket ON ticket_voids(ticket_id, id);
        CREATE TABLE IF NOT EXISTS sales_fixture (
          id INTEGER PRIMARY KEY,
          sale_no TEXT NOT NULL UNIQUE,
          sku_code TEXT NOT NULL,
          sold_at TEXT NOT NULL,
          unit_price REAL NOT NULL,
          qty INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hold_applies (
          id INTEGER PRIMARY KEY,
          ticket_id INTEGER,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        '''
    )


def _columns(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate(conn) -> None:
    """Bring older databases up to the current schema (additive only; history rows never deleted)."""
    ticket_cols = _columns(conn, "price_tickets")
    if "voided_at" not in ticket_cols:
        conn.execute("ALTER TABLE price_tickets ADD COLUMN voided_at TEXT")
    if "void_reason" not in ticket_cols:
        conn.execute("ALTER TABLE price_tickets ADD COLUMN void_reason TEXT")
    if "void_count" not in ticket_cols:
        conn.execute("ALTER TABLE price_tickets ADD COLUMN void_count INTEGER NOT NULL DEFAULT 0")

    history_cols = _columns(conn, "price_history")
    if "entry_type" not in history_cols:
        conn.execute("ALTER TABLE price_history ADD COLUMN entry_type TEXT NOT NULL DEFAULT 'apply'")
    if "ref_ticket_no" not in history_cols:
        conn.execute("ALTER TABLE price_history ADD COLUMN ref_ticket_no TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_price_history_sku ON price_history(sku_code, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ticket_voids_ticket ON ticket_voids(ticket_id, id)"
    )


def seed_if_empty() -> None:
    conn = connect()
    try:
        init_schema(conn)
        _migrate(conn)
        n = conn.execute("SELECT COUNT(*) c FROM skus").fetchone()["c"]
        if n:
            conn.commit()
            return

        skus = json.loads((FIXTURES / "skus.json").read_text(encoding="utf-8"))
        sales = json.loads((FIXTURES / "sales.json").read_text(encoding="utf-8"))
        now = _now()
        for s in skus:
            conn.execute(
                "INSERT INTO skus(sku_code, title, category, list_price, enabled) VALUES (?,?,?,?,1)",
                (s["sku_code"], s["title"], s["category"], float(s["list_price"])),
            )
            conn.execute(
                "INSERT INTO price_book(sku_code, current_price, source_ticket_no, effective_at, updated_at) VALUES (?,?,NULL,?,?)",
                (s["sku_code"], float(s["list_price"]), now, now),
            )
            conn.execute(
                "INSERT INTO price_history(sku_code, price, source_ticket_no, effective_at, recorded_at) VALUES (?,?,NULL,?,?)",
                (s["sku_code"], float(s["list_price"]), now, now),
            )
        for row in sales:
            conn.execute(
                "INSERT INTO sales_fixture(sale_no, sku_code, sold_at, unit_price, qty) VALUES (?,?,?,?,?)",
                (row["sale_no"], row["sku_code"], row["sold_at"], float(row["unit_price"]), int(row["qty"])),
            )
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES ('business_clock', ?)",
            ("2026-11-16T09:00:00Z",),
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES ('clock_label', ?)",
            ("业务钟（可拨，用于判断改价是否到期）",),
        )
        conn.commit()
    finally:
        conn.close()
