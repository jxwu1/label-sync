from datetime import date

from app.services import briefing


def test_data_week_uses_latest_complete_week():
    # 最新事件到 06-14(周日), as_of 06-16 → 06-08 当周已整周过去 → 用 06-08
    dw, complete = briefing.compute_data_week(date(2026, 6, 14), as_of=date(2026, 6, 16))
    assert dw == date(2026, 6, 8)
    assert complete is True


def test_data_week_saturday_latest_still_complete():
    """review #3: 希腊周日歇业, 最新销售=周六; 该周整周过去后必须算完整, 不能再跳一周。"""
    # 最新事件 06-13(周六), as_of 06-16(下周二) → 06-08 周完整 → 用 06-08
    dw, complete = briefing.compute_data_week(date(2026, 6, 13), as_of=date(2026, 6, 16))
    assert dw == date(2026, 6, 8)
    assert complete is True


def test_data_week_monday_morning_picks_last_week():
    # as_of 恰好下周一: 上周(06-08)整周已过去 → 完整
    dw, complete = briefing.compute_data_week(date(2026, 6, 13), as_of=date(2026, 6, 15))
    assert dw == date(2026, 6, 8)
    assert complete is True


def test_data_week_latest_week_complete_when_data_runs_to_sunday():
    # 最新事件到 06-07(周日), as_of 06-09 → 06-01 当周完整, 用 06-01
    dw, complete = briefing.compute_data_week(date(2026, 6, 7), as_of=date(2026, 6, 9))
    assert dw == date(2026, 6, 1)
    assert complete is True


def test_data_week_none_when_no_events():
    dw, complete = briefing.compute_data_week(None, as_of=date(2026, 6, 9))
    assert dw is None
    assert complete is False


def test_data_week_first_import_half_week_is_incomplete():
    # 首次导入: 最新事件所在周尚未整周过去, 且该周一之前没有任何事件 → 数据周未完整
    dw, complete = briefing.compute_data_week(
        latest_event_date=date(2026, 6, 10),
        as_of=date(2026, 6, 10),
        prior_complete_event_date=None,
    )
    assert dw is None
    assert complete is False


def test_data_week_uses_week_of_prior_event_when_current_incomplete():
    # 最新到 06-10, as_of 06-10(当周未过完); 周一(06-08)之前最近事件在 06-05 → 用 06-01
    dw, complete = briefing.compute_data_week(
        latest_event_date=date(2026, 6, 10),
        as_of=date(2026, 6, 10),
        prior_complete_event_date=date(2026, 6, 5),
    )
    assert dw == date(2026, 6, 1)
    assert complete is True


def test_data_week_skips_empty_prior_week_to_real_data_week():
    # 上一完整周(06-01)恰好零销, 当前周一之前最近事件其实在 05-20 → 落到有数据的 05-18 周
    dw, complete = briefing.compute_data_week(
        latest_event_date=date(2026, 6, 10),
        as_of=date(2026, 6, 10),
        prior_complete_event_date=date(2026, 5, 20),
    )
    assert dw == date(2026, 5, 18)
    assert complete is True


def test_sales_health_normal(monkeypatch):
    monkeypatch.setattr(
        briefing, "_forecast_covered_barcodes", lambda s: ["b1", "b2", "b3", "b4", "b5", "b6"]
    )
    monkeypatch.setattr(briefing, "_forecast_mu_sum", lambda s: 380.0)
    # 真实口径: BacktestResult.bias = mean(pred-actual) 的绝对件数 (review #4),
    # 不是分数; 0.89 件/周是 4 baseline 回测里实际出现过的量级。
    monkeypatch.setattr(briefing, "_latest_backtest_bias", lambda s: 0.89)

    def fake_bulk(barcodes, end_date, weeks, session):
        cur = date(2026, 6, 1)
        prev = date(2026, 5, 25)
        return {
            bc: {"series": {cur: 20, prev: 16}, "sku_type": "retail_dominant"} for bc in barcodes
        }

    monkeypatch.setattr(briefing, "_base_demand_views_bulk", fake_bulk)

    card = briefing.compute_sales_health(
        session=None, data_week=date(2026, 6, 1), data_week_complete=True
    )
    assert card["ok"] is True
    assert card["covered_skus"] == 6
    assert card["current_qty"] == 120
    assert card["previous_qty"] == 96
    assert card["delta_pct"] == 25.0
    assert card["forecast_next_total"] == 380.0
    assert card["model_bias_units"] == 0.9


def test_forecast_mu_sum_uses_mu_not_p50():
    """下期系统预期 = Σmu(均值, 可加), 不是 Σp50(中位数, 间歇需求下塌成0严重低估)。

    仅 retail_dominant/mixed 计入 (wholesale_only 不进零售需求口径)。
    """
    from app.models import ForecastOutput
    from app.repositories import stockpile_db

    with stockpile_db._session() as s:
        s.add_all(
            [
                ForecastOutput(
                    product_barcode="mu_b1",
                    model_used="EmpiricalQuantile",
                    sku_type="retail_dominant",
                    n_weeks_history=20,
                    mu=10.0,
                    sigma=1.0,
                    p50=0.0,
                    p98=30.0,  # 间歇: p50=0 但 mu=10
                ),
                ForecastOutput(
                    product_barcode="mu_b2",
                    model_used="EmpiricalQuantile",
                    sku_type="mixed",
                    n_weeks_history=20,
                    mu=5.0,
                    sigma=1.0,
                    p50=1.0,
                    p98=20.0,
                ),
                ForecastOutput(
                    product_barcode="mu_b3",
                    model_used="EmpiricalQuantile",
                    sku_type="wholesale_only",
                    n_weeks_history=20,
                    mu=100.0,
                    sigma=1.0,
                    p50=99.0,
                    p98=200.0,  # 不计入
                ),
            ]
        )
        s.commit()
        total = briefing._forecast_mu_sum(s)

    assert total == 15.0  # Σmu(10+5); 若误用 p50 会得 1.0; wholesale 的 100 被排除


def test_sales_health_coverage_insufficient(monkeypatch):
    monkeypatch.setattr(briefing, "_forecast_covered_barcodes", lambda s: ["b1", "b2"])
    monkeypatch.setattr(briefing, "_forecast_mu_sum", lambda s: 0.0)
    monkeypatch.setattr(briefing, "_latest_backtest_bias", lambda s: None)
    monkeypatch.setattr(
        briefing,
        "_base_demand_views_bulk",
        lambda barcodes, *a, **k: {
            bc: {"series": {date(2026, 6, 1): 5}, "sku_type": "mixed"} for bc in barcodes
        },
    )
    card = briefing.compute_sales_health(
        session=None, data_week=date(2026, 6, 1), data_week_complete=True
    )
    assert card["ok"] is True
    assert card["status"] == "coverage_insufficient"
    assert card["delta_pct"] is None


def test_sales_health_no_data_week(monkeypatch):
    card = briefing.compute_sales_health(session=None, data_week=None, data_week_complete=False)
    assert card["status"] == "week_incomplete"
    assert card["delta_pct"] is None


# ---------------------------------------------------------------------------
# Task 3 — 补货风险卡 + 建议补货列表
# ---------------------------------------------------------------------------


def _row(bc, **kw):
    base = {
        "barcode": bc,
        "model": bc.upper(),
        "qty_total": 10,
        "weekly_velocity": 2.0,
        "weeks_of_cover": 5.0,
        "restock_qty_p50": 6,
        "stockout_zero_weeks_last8": 0,
        "auto_category": "stable",
        "manual_category": None,
        "inventory_cost_value_eur": None,
        "is_truly_discontinued": False,
        "is_new_item": False,
        "urgency_score": 80,
    }
    base.update(kw)
    return base


def test_restock_risk_counts_and_urgent(monkeypatch):
    # 与补货页 KPI 同口径 (review round3): total = 关注+紧急(score>=40), urgent = 紧急(>=70)
    rows = [
        _row("a", urgency_score=75),
        _row("b", urgency_score=45),
        _row("c", restock_qty_p50=0, urgency_score=90),
        _row("d", urgency_score=None),
    ]
    monkeypatch.setattr(briefing, "_suppressed_barcodes", lambda s: set())
    card = briefing.compute_restock_risk(session=None, rows=rows)
    assert card["ok"] is True
    assert card["total"] == 2
    assert card["urgent"] == 1


def test_restock_candidates_exclude_low_urgency(monkeypatch):
    """review round3: p50>0 全集 ~1 万 SKU 对老板是噪音; 低分长尾(<40)和无分(新品等)不进简报。"""
    rows = [
        _row("hot", urgency_score=70),
        _row("watch", urgency_score=40),
        _row("calm", urgency_score=39.9),
        _row("none", urgency_score=None),
    ]
    monkeypatch.setattr(briefing, "_suppressed_barcodes", lambda s: set())
    card = briefing.compute_restock_risk(session=None, rows=rows)
    assert card["total"] == 2
    assert card["urgent"] == 1
    out = briefing.build_restock_actions(session=None, rows=rows)
    assert {i["barcode"] for i in out["items"]} == {"hot", "watch"}


def test_restock_candidates_exclude_disc_and_new(monkeypatch):
    """review #7: 与补货页 KPI 池同口径 — 真停用/新品不算补货候选, 否则两边数字对不上。"""
    rows = [
        _row("a"),
        _row("b", is_truly_discontinued=True),
        _row("c", is_new_item=True),
    ]
    monkeypatch.setattr(briefing, "_suppressed_barcodes", lambda s: set())
    card = briefing.compute_restock_risk(session=None, rows=rows)
    assert card["total"] == 1
    out = briefing.build_restock_actions(session=None, rows=rows)
    assert [i["barcode"] for i in out["items"]] == ["a"]


def test_restock_risk_excludes_suppressed(monkeypatch):
    rows = [_row("a"), _row("b")]
    monkeypatch.setattr(briefing, "_suppressed_barcodes", lambda s: {"a"})
    card = briefing.compute_restock_risk(session=None, rows=rows)
    assert card["total"] == 1


def test_restock_actions_sorted(monkeypatch):
    rows = [
        _row("a", weeks_of_cover=5.0, restock_qty_p50=6),
        _row("b", weeks_of_cover=1.0, restock_qty_p50=9),
        _row("d", weeks_of_cover=None, restock_qty_p50=20),
    ]
    monkeypatch.setattr(briefing, "_suppressed_barcodes", lambda s: set())
    out = briefing.build_restock_actions(session=None, rows=rows)
    assert out["ok"] is True
    assert [i["barcode"] for i in out["items"]] == ["b", "a", "d"]
    assert out["total"] == 3


def test_stockout_impact(monkeypatch):
    rows = [
        _row("a", stockout_zero_weeks_last8=3),
        _row("b", stockout_zero_weeks_last8=0),
        _row("c", stockout_zero_weeks_last8=5),
    ]
    card = briefing.compute_stockout_impact(rows=rows)
    assert card["ok"] is True
    assert card["total"] == 2
    assert [i["barcode"] for i in card["samples"]] == ["c", "a"]


def test_overstock_with_cost():
    # 真实域值: auto_category ∈ categorizer.CATEGORIES (无 'dying'),
    # manual_category ∈ 中文标签 (routes/analytics._VALID_MANUAL_CATEGORIES)
    rows = [
        _row("a", manual_category="滞销", qty_total=10, inventory_cost_value_eur=100.0),
        _row("b", auto_category="declining", qty_total=5, inventory_cost_value_eur=50.0),
        _row("c", auto_category="stable", qty_total=99, inventory_cost_value_eur=999.0),
    ]
    card = briefing.compute_overstock_risk(rows=rows)
    assert card["ok"] is True
    assert card["total"] == 2
    assert card["stock_qty"] == 15
    assert card["cost_available"] is True
    assert card["overstock_value_eur"] == 150.0


def test_overstock_cost_all_empty():
    rows = [
        _row("a", manual_category="滞销", qty_total=10, inventory_cost_value_eur=None),
        _row("b", auto_category="declining", qty_total=5, inventory_cost_value_eur=None),
    ]
    card = briefing.compute_overstock_risk(rows=rows)
    assert card["total"] == 2
    assert card["stock_qty"] == 15
    assert card["cost_available"] is False
    assert card["overstock_value_eur"] is None


def test_overstock_manual_slow_mover_tag_included():
    """老板手动标「滞销」必须计入压货, 即使 auto 是 stable (review #2)。"""
    rows = [_row("a", manual_category="滞销", auto_category="stable", qty_total=3)]
    card = briefing.compute_overstock_risk(rows=rows)
    assert card["total"] == 1


def test_overstock_other_manual_tag_does_not_shadow_declining():
    """非滞销的手动标签不能遮蔽 auto declining (review #2: manual or auto 旧写法的 bug)。"""
    rows = [_row("a", manual_category="长期产品", auto_category="declining", qty_total=3)]
    card = briefing.compute_overstock_risk(rows=rows)
    assert card["total"] == 1


def test_overstock_partial_cost_reports_coverage():
    """review #9: 只有部分 SKU 有成本时, 金额必须带 costed_skus/total 口径, 不能冒充总额。"""
    rows = [
        _row("a", auto_category="declining", qty_total=10, inventory_cost_value_eur=3.0),
        _row("b", auto_category="declining", qty_total=20, inventory_cost_value_eur=None),
        _row("c", auto_category="declining", qty_total=30, inventory_cost_value_eur=None),
    ]
    card = briefing.compute_overstock_risk(rows=rows)
    assert card["total"] == 3
    assert card["cost_available"] is True
    assert card["overstock_value_eur"] == 3.0
    assert card["costed_skus"] == 1


def test_overstock_excludes_stable_and_new():
    rows = [
        _row("a", auto_category="stable", qty_total=10),
        _row("b", auto_category="new", qty_total=10),
        _row("c", auto_category="unclassified", qty_total=10),
    ]
    card = briefing.compute_overstock_risk(rows=rows)
    assert card["total"] == 0


def test_data_health_cost_coverage(monkeypatch):
    rows = [
        _row("a", inventory_cost_value_eur=10.0),
        _row("b", inventory_cost_value_eur=None),
        _row("c", inventory_cost_value_eur=20.0),
        _row("d", inventory_cost_value_eur=None),
    ]
    monkeypatch.setattr(
        briefing,
        "_freshness",
        lambda: {"last_import_date": "2026-06-08", "days_since": 1, "stale": False},
    )
    card = briefing.compute_data_health(rows=rows)
    assert card["ok"] is True
    assert card["stale"] is False
    assert card["cost_coverage_pct"] == 50.0


def test_data_health_empty_rows(monkeypatch):
    monkeypatch.setattr(
        briefing,
        "_freshness",
        lambda: {"last_import_date": None, "days_since": None, "stale": False},
    )
    card = briefing.compute_data_health(rows=[])
    assert card["cost_coverage_pct"] is None


def test_review_actions_sorted(monkeypatch):
    report = {
        "negative_stock": {"count": 12, "samples": [{"product_barcode": "x"}]},
        "unknown_prefix": {"count": 0, "samples": []},
        "flippers": {"count": 5, "samples": []},
        "scanned_count": 999,
    }
    monkeypatch.setattr(briefing, "_quality_report", lambda: report)
    out = briefing.build_review_actions()
    assert out["ok"] is True
    assert [i["kind"] for i in out["items"]] == ["negative_stock", "flippers"]
    assert out["items"][0]["count"] == 12


# ---------------------------------------------------------------------------
# Task 7 — 建议催/确认列表
# ---------------------------------------------------------------------------


def test_follow_up_overdue_sort(monkeypatch):
    orders = [
        {
            "id": 1,
            "supplier_id": "S1",
            "supplier_name": "供应商1",
            "order_date": "2026-05-01",
            "status": "placed",
            "total_qty": 100,
        },
        {
            "id": 2,
            "supplier_id": "S2",
            "supplier_name": "供应商2",
            "order_date": "2026-06-01",
            "status": "placed",
            "total_qty": 50,
        },
        {
            "id": 3,
            "supplier_id": "S1",
            "supplier_name": "供应商1",
            "order_date": "2026-05-20",
            "status": "arrived",
            "total_qty": 10,
        },
    ]
    monkeypatch.setattr(briefing, "_list_orders", lambda: orders)
    monkeypatch.setattr(briefing, "_supplier_lead_days", lambda: {"S1": 10, "S2": 10})
    out = briefing.build_follow_up_actions(as_of=date(2026, 6, 9))
    assert out["ok"] is True
    assert out["total"] == 2
    assert out["items"][0]["id"] == 1
    assert out["items"][0]["overdue_days"] == 29
    assert out["items"][0]["overdue_state"] == "overdue"


def test_follow_up_not_yet_due_gets_not_due_state(monkeypatch):
    """review #8: 未到期订单 overdue_days 为负, 必须标 not_due, 不能渲染「逾期 -13 天」。"""
    orders = [
        {
            "id": 1,
            "supplier_id": "S1",
            "supplier_name": "供应商1",
            "order_date": "2026-06-08",
            "status": "placed",
            "total_qty": 100,
        },
    ]
    monkeypatch.setattr(briefing, "_list_orders", lambda: orders)
    monkeypatch.setattr(briefing, "_supplier_lead_days", lambda: {"S1": 14})
    out = briefing.build_follow_up_actions(as_of=date(2026, 6, 9))
    item = out["items"][0]
    assert item["overdue_days"] == -13
    assert item["overdue_state"] == "not_due"


def test_follow_up_no_lead_time_fallback(monkeypatch):
    orders = [
        {
            "id": 1,
            "supplier_id": "S9",
            "supplier_name": "X",
            "order_date": "2026-06-01",
            "status": "placed",
            "total_qty": 5,
        },
        {
            "id": 2,
            "supplier_id": "S9",
            "supplier_name": "X",
            "order_date": "2026-05-01",
            "status": "placed",
            "total_qty": 7,
        },
    ]
    monkeypatch.setattr(briefing, "_list_orders", lambda: orders)
    monkeypatch.setattr(briefing, "_supplier_lead_days", lambda: {})
    out = briefing.build_follow_up_actions(as_of=date(2026, 6, 9))
    assert out["items"][0]["id"] == 2
    assert out["items"][0]["overdue_days"] is None
    assert out["items"][0]["overdue_state"] == "unknown"


def test_follow_up_empty(monkeypatch):
    monkeypatch.setattr(briefing, "_list_orders", lambda: [])
    monkeypatch.setattr(briefing, "_supplier_lead_days", lambda: {})
    out = briefing.build_follow_up_actions(as_of=date(2026, 6, 9))
    assert out["ok"] is True
    assert out["status"] == "empty"
    assert out["items"] == []


# ---------------------------------------------------------------------------
# Task 9 — build_briefing 聚合编排 + _safe 块隔离
# ---------------------------------------------------------------------------


def _patch_briefing_seams(monkeypatch):
    """build_briefing 的取数 seam 全部打桩, 避免触真实 DB。"""
    monkeypatch.setattr(briefing, "_load_rows", lambda: [_row("a", stockout_zero_weeks_last8=2)])
    monkeypatch.setattr(briefing, "_latest_event_date", lambda: date(2026, 6, 10))
    monkeypatch.setattr(briefing, "_event_date_before", lambda before: date(2026, 6, 5))
    monkeypatch.setattr(briefing, "_suppressed_barcodes", lambda s: set())
    monkeypatch.setattr(
        briefing,
        "_freshness",
        lambda: {"last_import_date": "2026-06-08", "days_since": 1, "stale": False},
    )
    monkeypatch.setattr(briefing, "_list_orders", lambda: [])
    monkeypatch.setattr(briefing, "_supplier_lead_days", lambda: {})
    monkeypatch.setattr(briefing, "_quality_report", lambda: {})


def test_build_briefing_isolates_block_failure(monkeypatch):
    _patch_briefing_seams(monkeypatch)

    # 业务信号错误(非 DB) → 该块降级, 其余块照常
    def business_boom(*a, **k):
        raise ValueError("某业务口径算不出来")

    monkeypatch.setattr(briefing, "compute_sales_health", business_boom)

    out = briefing.build_briefing(as_of=date(2026, 6, 9), generated_at="2026-06-09T13:40:00")
    assert out["ok"] is True
    assert out["cards"]["sales_health"]["ok"] is False
    assert "error" in out["cards"]["sales_health"]
    assert out["cards"]["stockout_impact"]["ok"] is True
    assert out["cards"]["stockout_impact"]["total"] == 1
    assert out["data_week"] == "2026-06-01"


def test_build_briefing_propagates_system_error(monkeypatch):
    # 系统级错误(schema 缺列 / 表不存在 = SQLAlchemyError) **不**吞成业务降级,
    # 必须上抛 → 路由层返回 5xx (spec §6)。
    import pytest
    from sqlalchemy.exc import ProgrammingError

    _patch_briefing_seams(monkeypatch)

    def schema_boom(*a, **k):
        raise ProgrammingError("SELECT ...", {}, Exception("column does not exist"))

    monkeypatch.setattr(briefing, "compute_stockout_impact", schema_boom)

    with pytest.raises(ProgrammingError):
        briefing.build_briefing(as_of=date(2026, 6, 9), generated_at="2026-06-09T13:40:00")


def test_sales_health_rounds_forecast_total(monkeypatch):
    """下期系统预期是件数, 取整 (Σmu 带小数, 不能显 17572.170751934093)。"""
    monkeypatch.setattr(
        briefing, "_forecast_covered_barcodes", lambda s: ["b1", "b2", "b3", "b4", "b5", "b6"]
    )
    monkeypatch.setattr(briefing, "_forecast_mu_sum", lambda s: 17572.170751934093)
    monkeypatch.setattr(briefing, "_latest_backtest_bias", lambda s: 0.2)
    monkeypatch.setattr(
        briefing,
        "_base_demand_views_bulk",
        lambda barcodes, *a, **k: {
            bc: {"series": {date(2026, 6, 1): 20, date(2026, 5, 25): 16}, "sku_type": "retail_dominant"}
            for bc in barcodes
        },
    )
    card = briefing.compute_sales_health(
        session=None, data_week=date(2026, 6, 1), data_week_complete=True
    )
    assert card["forecast_next_total"] == 17572
    assert isinstance(card["forecast_next_total"], int)
