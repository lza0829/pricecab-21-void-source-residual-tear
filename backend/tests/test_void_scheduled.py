"""场景一：作废未生效（scheduled）改价单。"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _make_ticket(client: TestClient, effective_at: str = "2026-11-20T10:00:00Z") -> dict:
    r = client.post(
        "/api/tickets",
        json={
            "title": "误建的促销单",
            "effective_at": effective_at,
            "note": None,
            "lines": [{"sku_code": "SKU-TEA-001", "new_price": 88.8}],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_policy_is_global_and_single(client: TestClient):
    r = client.get("/api/tickets/void-policy")
    assert r.status_code == 200
    body = r.json()
    # 全局唯一互斥策略：本系统只实现 applied_rollback，不存在另一种命运的分支。
    assert body["applied_void_policy"] == "applied_rollback"
    assert body["allows_void_applied"] is True


def test_void_scheduled_requires_reason(client: TestClient):
    t = _make_ticket(client)
    r = client.post(f"/api/tickets/{t['id']}/void", json={"reason": "   "})
    assert r.status_code == 400
    r = client.post(f"/api/tickets/{t['id']}/void", json={})
    assert r.status_code == 400


def test_void_scheduled_then_never_due_again(client: TestClient):
    # 生效时刻早于业务钟，本应到期；作废后不得再被到期扫到/应用。
    t = _make_ticket(client, effective_at="2026-11-10T10:00:00Z")
    r = client.post(f"/api/tickets/{t['id']}/void", json={"reason": "误建，撤回"})
    assert r.status_code == 200, r.text
    body = r.json()

    # 互证：单状态、作废次数、留痕原因
    assert body["status"] == "voided"
    assert body["void_count"] == 1
    assert body["void_reason"] == "误建，撤回"
    assert body["voided_at"]
    assert len(body["voids"]) == 1
    assert body["voids"][0]["status_before"] == "scheduled"
    assert body["rolled_back_lines"] == 0  # 未应用单无价签可回退

    # 重复作废被拒
    r2 = client.post(f"/api/tickets/{t['id']}/void", json={"reason": "再来一次"})
    assert r2.status_code == 409

    # 应用到期：该单不得被写出新的应用成功
    r3 = client.post("/api/apply/due")
    assert r3.status_code == 200
    applied = r3.json()
    assert applied["applied"] is False or t["ticket_no"] not in applied.get("tickets", [])

    # 再次查单，仍是作废态，次数不增加
    detail = client.get(f"/api/tickets/{t['id']}").json()
    assert detail["status"] == "voided"
    assert detail["void_count"] == 1

    # 价签本没有被该单污染
    book = {b["sku_code"]: b for b in client.get("/api/prices/book").json()}
    assert book["SKU-TEA-001"]["source_ticket_no"] != t["ticket_no"]


def test_void_nonexistent_ticket_404(client: TestClient):
    r = client.post("/api/tickets/9999/void", json={"reason": "x"})
    assert r.status_code == 404
