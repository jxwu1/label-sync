"""/ui/restock 浏览器烟雾（补货页 Vue Phase 1）。

自建夹具：直接 merge 一行物化 SkuSummary（as_of=今天, payload=完整字段），
list_sku_summary() 表优先路径即返回它 → /api/restock/items 投影 + strict 校验
→ 表格渲染 ≥1 行。不依赖 stockpile/inventory_events 全量计算，不依赖导入顺序。

前置：frontend/dist 必须已构建（gitignore）。标准命令 = `npm run build` → `pytest e2e/`。
dist 缺失时 skip（非 fail），CI e2e-smoke job 有构建步骤故必跑（见 project_e2e_harness）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

_DIST_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html"

requires_dist = pytest.mark.skipif(
    not _DIST_INDEX.exists(),
    reason="frontend/dist 未构建——先跑 `npm run build`（CI e2e-smoke 有构建步骤）",
)


def _payload(barcode: str = "5201234567890") -> dict:
    # 超集：含 RestockItem（列表页）+ RestockDetail（drawer）所有字段，
    # 验证 strict 投影不被击穿，同时保证 drawer detail 端点能通过 schema 校验。
    return {
        # ── RestockItem（列表页）字段 ──────────────────────────────────
        "barcode": barcode,
        "model": "ABC123",
        "name_zh": "测试品",
        "origin": "FOREIGN",
        "supplier_id": "GR001",
        "is_truly_discontinued": False,
        "is_new_item": False,
        "qty_total": 100,
        "weeks_of_cover": 2.0,
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
        "urgency_score": 88.5,
        "stockout_zero_weeks_last8": 0,
        # ── RestockDetail（drawer）追加字段 ───────────────────────────
        # NON-NULL in RestockDetail schema:
        "total_qty": 100,
        "lifetime_purchase_qty": 200,
        "lifetime_sale_qty": 150,
        "lifetime_sale_revenue_eur": 870.0,
        "n_active_weeks_26w": 18,
        "retail_qty_26w": 3,
        "retail_revenue_26w": 17.4,
        "retail_share_26w": 0.24,
        "is_history_truncated": False,
        # Optional:
        "inventory_sale_value_eur": 600.0,
        "lifetime_invested_eur": 640.0,
        "net_cashflow_eur": 230.0,
        "inventory_imbalance_pct": 5.2,
        "first_event_at": "2024-01-15",
        "retail_price_observed": 6.0,
        "retail_price_estimate": 5.9,
        # urgency_breakdown: full 7-key RestockDetailUrgencyBreakdown
        "urgency_breakdown": {
            "velocity": 30.0,
            "cover": 22.5,
            "recency": 8.0,
            "margin": 28.0,
            "demand_validity": 1.0,
            "velocity_pctile": 0.85,
            "margin_pctile": 0.93,
        },
    }


@pytest.fixture
def seed_restock(live_server):
    from app.models import SkuSummary, get_session
    from app.services.analytics.summary import clear_list_sku_summary_cache

    as_of = datetime.now().date().isoformat()
    with get_session() as s:
        s.merge(SkuSummary(product_barcode="5201234567890", as_of=as_of, payload=_payload()))
    # 清 60s 内存缓存：其他 smoke 可能已用空库填了缓存
    clear_list_sku_summary_cache()
    return live_server


@pytest.mark.smoke
@requires_dist
def test_restock_ui_renders_rows(seed_restock, page_with_console):
    page = page_with_console
    page.goto(f"{seed_restock}/ui/restock")
    page.wait_for_selector("tr.rs-row", timeout=10000)
    assert page.locator("tr.rs-row").count() >= 1
    # 投影白名单生效：胖字段 urgency_breakdown 不应泄漏到任何渲染文本
    assert "urgency_breakdown" not in page.locator("#pageRestock").inner_text()
    # 默认 origin=FOREIGN → GR 徽标在；urgency 88.5 浮点原样显示（float 修复回归）
    assert "88.5" in page.locator("tr.rs-row").first.inner_text()
    # spec §9 验收：KPI 有数——seed 项 urgency 88.5≥70 → 「紧急」计数 = 1（非占位 —）
    hot = page.locator(".rs-kpi[data-tone='error'] .rs-kpi-num")
    assert hot.inner_text().strip() == "1", f"紧急 KPI 期望 1，实际 {hot.inner_text()!r}"
    assert page.console_errors == [], f"console errors: {page.console_errors}"


@pytest.mark.smoke
@requires_dist
def test_restock_drawer_expands(seed_restock, page_with_console):
    page = page_with_console
    page.goto(f"{seed_restock}/ui/restock")
    page.wait_for_selector("tr.rs-row", timeout=10000)
    page.locator("tr.rs-row").first.click()
    page.wait_for_selector("tr.rs-drawer-row", timeout=10000)
    assert page.locator(".rs-drawer-sec").count() >= 1
    drawer_text = page.locator("tr.rs-drawer-row").inner_text()
    assert "累计批发" in drawer_text
    assert "真实零售" in drawer_text
    assert page.console_errors == [], f"console errors: {page.console_errors}"
