"""GET /api/restock/suppressed：补货抑制集 canonical 端点（pydantic 契约，Vue Phase 1）。

只读，复用 restock_decisions.list_suppressed。鉴权镜像 tests/test_history_api.py
（X-Upload-Token cron 旁路）。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas_api import RestockSuppressedEntry, RestockSuppressedList


def test_suppressed_entry_accepts_full_and_null_reason():
    e = RestockSuppressedEntry.model_validate(
        {"skipped_at": "2026-06-10 09:00:00", "reason": None, "days_left": 4}
    )
    assert e.days_left == 4


def test_suppressed_entry_rejects_extra_key():
    with pytest.raises(ValidationError):
        RestockSuppressedEntry.model_validate(
            {"skipped_at": "x", "reason": None, "days_left": 1, "junk": 1}
        )


def test_suppressed_list_empty_ok():
    m = RestockSuppressedList.model_validate({"ok": True, "items": {}})
    assert m.items == {}


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def test_api_restock_suppressed_shape(real_app):
    resp = real_app.test_client().get(
        "/api/restock/suppressed", headers={"X-Upload-Token": "test-token-123"}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert isinstance(data["items"], dict)


from app.schemas_api import RestockItem


def _full_item():
    return {
        "barcode": "5201234567890",
        "model": "ABC123",
        "name_zh": "测试品",
        "origin": "FOREIGN",
        "supplier_id": "GR001",
        "is_truly_discontinued": False,
        "is_new_item": False,
        "qty_total": 100,
        "weeks_of_cover": 8.0,
        "weekly_velocity": 12.5,
        "weekly_revenue": 80.0,
        "margin_pct": 35.0,
        "margin_source": "purchase",
        "margin_price_source": "master",
        "master_stock_price_eur": 3.2,
        "master_sale_price_eur": 6.0,
        "last_purchase_unit_price": 3.0,
        "sale_net_avg": 5.8,
        "weekly_qty_12w": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        "trend_slope_pct_per_week": 1.2,
        "realized_profit_eur": 500.0,
        "inventory_cost_value_eur": 320.0,
        "last_purchase_days_ago": 20,
        "last_purchase_at": "2026-05-30",
        "restock_qty_p50": 50,
        "restock_qty_p98": 90,
        "restock_source": "p98_hist",
        "last_purchase_qty": 60,
        "urgency_score": 72,
        "stockout_zero_weeks_last8": 0,
    }


def test_restock_item_full_ok():
    m = RestockItem.model_validate(_full_item())
    assert m.urgency_score == 72


def test_restock_item_urgency_score_accepts_fractional():
    # 真实 list_sku_summary() 的 urgency_score 是浮点（如 69.5「次紧迫」），
    # 小数位有业务语义（供应商概览 max 排序 + 旧页直接显示原值 restock.js:152/835）。
    # schema 若写 int 会在真实数据上 500（15269 行全挂）。
    d = _full_item()
    d["urgency_score"] = 69.5
    m = RestockItem.model_validate(d)
    assert m.urgency_score == 69.5


def test_restock_item_nullable_fields_accept_none():
    it = _full_item()
    for k in [
        "model",
        "name_zh",
        "supplier_id",
        "qty_total",
        "weeks_of_cover",
        "margin_pct",
        "margin_source",
        "margin_price_source",
        "master_stock_price_eur",
        "master_sale_price_eur",
        "last_purchase_unit_price",
        "sale_net_avg",
        "trend_slope_pct_per_week",
        "realized_profit_eur",
        "inventory_cost_value_eur",
        "last_purchase_days_ago",
        "last_purchase_at",
        "restock_qty_p50",
        "restock_qty_p98",
        "restock_source",
        "last_purchase_qty",
        "urgency_score",
    ]:
        d = _full_item()
        d[k] = None
        RestockItem.model_validate(d)  # must not raise


@pytest.mark.parametrize(
    "field",
    [
        "origin",
        "weekly_velocity",
        "weekly_revenue",
        "weekly_qty_12w",
        "stockout_zero_weeks_last8",
        "is_truly_discontinued",
        "is_new_item",
        "barcode",
    ],
)
def test_restock_item_nonnull_fields_reject_none(field):
    d = _full_item()
    d[field] = None
    with pytest.raises(ValidationError):
        RestockItem.model_validate(d)


def test_restock_item_rejects_extra_key():
    d = _full_item()
    d["urgency_breakdown"] = {"velocity": 30}
    with pytest.raises(ValidationError):
        RestockItem.model_validate(d)


@pytest.mark.parametrize("bad", ["HZ", "XX", "GR"])
def test_restock_item_origin_enum_rejects_unknown_value(bad):
    d = _full_item()
    d["origin"] = bad
    with pytest.raises(ValidationError):
        RestockItem.model_validate(d)


from app.routes.restock import _ITEM_KEYS, _project_item


def test_project_item_key_set_equals_whitelist():
    fat = {
        **_full_item(),
        "urgency_breakdown": {"velocity": 30},
        "total_qty": 5,
        "retail_qty_26w": 3,
        "lifetime_invested_eur": 99.0,
    }
    out = _project_item(fat)
    assert set(out.keys()) == set(_ITEM_KEYS)
    assert "urgency_breakdown" not in out


def test_api_restock_items_returns_projected_rows(real_app):
    resp = real_app.test_client().get(
        "/api/restock/items", headers={"X-Upload-Token": "test-token-123"}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert isinstance(data["items"], list)
    assert data["total"] == len(data["items"])
    for row in data["items"]:
        assert set(row.keys()) == set(_ITEM_KEYS)
