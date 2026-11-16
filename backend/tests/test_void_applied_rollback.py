"""场景二：所选唯一策略（applied_rollback）下对已应用单的处理。

互证链：作废次数、单状态、价签本、历史末行与应用批次原计数必须互相印证。
"""
from __future__ import annotations

from fastapi.testclient import TestClient


SKU = "SKU-TEA-001"
CLOCK = "2026-11-16T09:00:00Z"


def _book(client: TestClient) -> dict:
    return {b["sku_code"]: b for b in client.get("/api/prices/book").json()}


def _history_for(client: TestClient, sku: str) -> list[dict]:
    return client.get(f"/api/prices/history?sku_code={sku}").json()


def _create_and_apply(client: TestClient, ticket_no_price: list[tuple[str, float]], at: str):
    for title, price in ticket_no_price:
        r = client.post(
            "/api/tickets",
            json={
                "title": title,
                "effective_at": at,
                "lines": [{"sku_code": SKU, "new_price": price}],
            },
        )
        assert r.status_code == 200, r.text
    r = client.post("/api/apply/due")
    assert r.status_code == 200, r.text
    return r.json()


def test_void_applied_rolls_back_book_and_keeps_audit(client: TestClient):
    baseline = _book(client)[SKU]["current_price"]

    applied = _create_and_apply(client, [("第一次改价", 33.3)], "2026-11-16T08:00:00Z")
    assert applied["applied"] is True
    batch_no = applied["batch_no"]
    ticket_no = applied["tickets"][0]

    # 应用后：价签本指向该单，历史末行是该单的 apply
    book = _book(client)
    assert book[SKU]["current_price"] == 33.3
    assert book[SKU]["source_ticket_no"] == ticket_no
    hist = _history_for(client, SKU)
    assert hist[0]["entry_type"] == "apply"
    assert hist[0]["ref_ticket_no"] == ticket_no
    history_rows_before = len(hist)

    # 作废已应用单
    tickets = {t["ticket_no"]: t for t in client.get("/api/tickets").json()}
    tid = tickets[ticket_no]["id"]
    r = client.post(f"/api/tickets/{tid}/void", json={"reason": "价格录错，按历史回退"})
    assert r.status_code == 200, r.text
    body = r.json()

    # 互证 1：单状态/次数/留痕
    assert body["status"] == "voided"
    assert body["void_count"] == 1
    assert body["void_reason"] == "价格录错，按历史回退"
    assert body["rolled_back_lines"] == 1
    assert body["voids"][0]["status_before"] == "applied"

    # 互证 2：价签本回到应用前基线价，来源单不再指向被作废单
    book2 = _book(client)
    assert book2[SKU]["current_price"] == baseline
    assert book2[SKU]["source_ticket_no"] != ticket_no

    # 互证 3：历史只追加、不删除——末行是 rollback，原 apply 行仍在
    hist2 = _history_for(client, SKU)
    assert len(hist2) == history_rows_before + 1
    assert hist2[0]["entry_type"] == "rollback"
    assert hist2[0]["ref_ticket_no"] == ticket_no
    assert hist2[0]["price"] == baseline
    apply_rows = [h for h in hist2 if h["entry_type"] == "apply" and h["ref_ticket_no"] == ticket_no]
    assert len(apply_rows) == 1  # 原应用行保留只读审计，没有被抹掉

    # 互证 4：应用批次原计数不变（不得回改批次）
    batches = {b["batch_no"]: b for b in client.get("/api/apply/batches").json()}
    assert batches[batch_no]["ticket_count"] == applied["ticket_count"]
    assert batches[batch_no]["line_count"] == applied["line_count"]
    assert batches[batch_no]["status"] == "done"

    # 作废后该单不会再被到期应用
    again = client.post("/api/apply/due").json()
    assert again.get("applied") is False or ticket_no not in again.get("tickets", [])


def test_void_latest_ticket_restores_most_recent_predecessor(client: TestClient):
    """连续两张已应用单，作废后一张时，价签应回退到前一张的价（历史末行的前驱）。"""
    first = _create_and_apply(client, [("第一单", 33.3)], "2026-11-16T08:00:00Z")
    first_no = first["tickets"][0]

    second = _create_and_apply(client, [("第二单", 44.4)], "2026-11-16T08:30:00Z")
    second_no = second["tickets"][0]

    assert _book(client)[SKU]["current_price"] == 44.4

    tickets = {t["ticket_no"]: t for t in client.get("/api/tickets").json()}
    r = client.post(
        f"/api/tickets/{tickets[second_no]['id']}/void",
        json={"reason": "第二单作废，回到第一单价"},
    )
    assert r.status_code == 200, r.text

    book = _book(client)
    assert book[SKU]["current_price"] == 33.3
    assert book[SKU]["source_ticket_no"] == first_no

    # 第一单的 apply 历史行依旧保留
    hist = _history_for(client, SKU)
    assert any(
        h["entry_type"] == "apply" and h["ref_ticket_no"] == second_no for h in hist
    )
    assert hist[0]["entry_type"] == "rollback"
    assert hist[0]["price"] == 33.3


def test_void_older_applied_ticket_does_not_overwrite_newer_book(client: TestClient):
    """更早的单被作废，但价签本已被更新的单接管：只留审计，不覆盖更新的价签。"""
    first = _create_and_apply(client, [("第一单", 33.3)], "2026-11-16T08:00:00Z")
    first_no = first["tickets"][0]
    _create_and_apply(client, [("第二单", 44.4)], "2026-11-16T08:30:00Z")

    assert _book(client)[SKU]["current_price"] == 44.4
    tickets = {t["ticket_no"]: t for t in client.get("/api/tickets").json()}
    r = client.post(
        f"/api/tickets/{tickets[first_no]['id']}/void",
        json={"reason": "旧单作废但新单已接管价签", },
    )
    assert r.status_code == 200, r.text

    # 价签本仍是更新的单的价，不被旧单回退覆盖
    book = _book(client)
    assert book[SKU]["current_price"] == 44.4
    # 但审计回退行仍然只追加存在
    hist = _history_for(client, SKU)
    assert hist[0]["entry_type"] == "rollback"
    assert hist[0]["ref_ticket_no"] == first_no


def test_reconcile_still_reads_history_after_rollback(client: TestClient):
    """回退历史行参与对账时间轴，且没有静默删除任何历史行。"""
    before = len(_history_for(client, SKU))
    applied = _create_and_apply(client, [("改价", 33.3)], "2026-11-16T08:00:00Z")
    tid = {t["ticket_no"]: t for t in client.get("/api/tickets").json()}[
        applied["tickets"][0]
    ]["id"]
    r = client.post(f"/api/tickets/{tid}/void", json={"reason": "回退对账验证"})
    assert r.status_code == 200
    after = len(_history_for(client, SKU))
    assert after == before + 2  # 一条 apply + 一条 rollback，均保留

    recon = client.get("/api/reconcile/sales")
    assert recon.status_code == 200
    assert recon.json()["sale_count"] >= 1
