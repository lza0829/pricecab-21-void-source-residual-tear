"""场景三：应用与作废并发冲突必须被拒，且任何一方成功后另一方不得再产生效果。"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app.engines.guards import ticket_write_guard


SKU = "SKU-TEA-001"


def _scheduled_ticket(client: TestClient, effective_at: str) -> dict:
    r = client.post(
        "/api/tickets",
        json={
            "title": "并发冲突单",
            "effective_at": effective_at,
            "lines": [{"sku_code": SKU, "new_price": 51.5}],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_void_rejected_while_apply_in_flight(client: TestClient):
    from app.engines.guards import write_lock_busy

    t = _scheduled_ticket(client, "2026-11-10T10:00:00Z")  # already due
    outcome: dict = {}

    def apply():
        # Hold the global write lock for the whole apply, then really apply.
        with ticket_write_guard("应用"):
            from app.services.apply_service import apply_due

            outcome["apply"] = apply_due()

    th = threading.Thread(target=apply)
    th.start()
    while not write_lock_busy():
        pass  # wait until the apply thread actually holds the lock

    r = client.post(f"/api/tickets/{t['id']}/void", json={"reason": "与应用并发"})
    th.join()

    assert r.status_code == 409
    assert "应用正在进行，作废被拒绝" in r.json()["detail"]
    # Apply succeeded; ticket is applied, never voided.
    detail = client.get(f"/api/tickets/{t['id']}").json()
    assert detail["status"] == "applied"
    assert detail["void_count"] == 0
    assert outcome["apply"]["applied"] is True


def test_apply_rejected_while_void_in_flight(client: TestClient):
    from app.engines import guards

    t = _scheduled_ticket(client, "2026-11-10T10:00:00Z")  # due, but void wins
    started = threading.Event()
    release = threading.Event()

    def hold_void_lock():
        with guards._write_lock:
            started.set()
            release.wait(5.0)  # keep holding until the main thread says so

    th = threading.Thread(target=hold_void_lock)
    th.start()
    started.wait(1.0)
    try:
        r = client.post("/api/apply/due")
        assert r.status_code == 409
        assert "作废正在进行，应用被拒绝" in r.json()["detail"]
    finally:
        release.set()
        th.join()

    # No batch was created and the ticket is still scheduled.
    detail = client.get(f"/api/tickets/{t['id']}").json()
    assert detail["status"] == "scheduled"
    batches = client.get("/api/apply/batches").json()
    assert all(b["status"] != "running" for b in batches)


def test_void_then_apply_never_writes_ticket(client: TestClient):
    """Sequential close-out: once voided, a later apply can never write that ticket."""
    t = _scheduled_ticket(client, "2026-11-10T10:00:00Z")
    r = client.post(f"/api/tickets/{t['id']}/void", json={"reason": "先作废"})
    assert r.status_code == 200

    res = client.post("/api/apply/due").json()
    assert t["ticket_no"] not in res.get("tickets", [])

    detail = client.get(f"/api/tickets/{t['id']}").json()
    assert detail["status"] == "voided"
    assert detail["void_count"] == 1
    book = {b["sku_code"]: b for b in client.get("/api/prices/book").json()}
    assert book[SKU]["source_ticket_no"] != t["ticket_no"]


def test_conditional_update_blocks_cross_connection_race(client: TestClient, monkeypatch):
    """Even bypassing the in-process lock, the DB conditional update rejects a racing void."""
    import sqlite3

    from app.repositories import tickets as ticket_repo
    from app.db import connect

    t = _scheduled_ticket(client, "2026-11-10T10:00:00Z")
    # Simulate the apply having won the state transition in another connection.
    other = connect(immediate=True)
    try:
        ticket_repo.mark_applied(other, t["id"], applied_at="2026-11-16T09:00:00Z", batch_id=1)
        other.commit()
    finally:
        other.close()

    conn = connect()
    try:
        # mark_voided on an already-applied row still succeeds (applied is voidable),
        # but re-void on the now-voided row must change nothing.
        first = ticket_repo.mark_voided(conn, t["id"], voided_at="2026-11-16T09:05:00Z", reason="x")
        assert first == 1
        second = ticket_repo.mark_voided(conn, t["id"], voided_at="2026-11-16T09:06:00Z", reason="y")
        assert second == 0
        conn.commit()
    finally:
        conn.close()

    # A scheduled->applied conditional update on a voided ticket must raise.
    conn2 = connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            ticket_repo.mark_applied(conn2, t["id"], applied_at="2026-11-16T09:07:00Z", batch_id=2)
    finally:
        conn2.close()
