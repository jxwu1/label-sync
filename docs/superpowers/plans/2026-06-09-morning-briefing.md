# 最新批次简报（晨间简报）v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增只读「最新批次简报」页（老板 backlog #3），把 5 个经营信号卡片 + 3 个行动列表聚合到一页，复用现有物化表与服务，不建表不加 cron。

**Architecture:** 新增 `app/services/briefing.py`（纯聚合编排，调现有服务）+ `app/routes/briefing.py`（`GET /briefing` 页面 + `GET /briefing/data` JSON）+ 前端 partial/nav 项。业务块失败返回 `200 + ok=false` 局部降级；系统级失败抛错走 5xx。数据周固定为「最新完整 ISO 周」。

**Tech Stack:** Python 3.12 / Flask / SQLAlchemy 2.x / pytest / Alpine.js + Tailwind。

**Spec:** `docs/superpowers/specs/2026-06-09-morning-briefing-design.md`（已批准）。

---

## 关键既有依赖（已核实，实现时直接调用）

| 用途 | 调用 | 返回要点 |
|---|---|---|
| 全 SKU 汇总（物化，60s 缓存） | `app.services.analytics.summary.list_sku_summary()` → `list[dict]` | 每行含 `barcode/model/name_zh/auto_category/manual_category/origin/qty_total/weekly_velocity/weeks_of_cover/restock_qty_p50/restock_source/forecast_p50/stockout_zero_weeks_last8/inventory_cost_value_eur/inventory_sale_value_eur/urgency_score` |
| 数据新鲜度 | `app.services.analytics.freshness.get_data_freshness()` | `{last_import_date, days_since, stale, last_scrape_success_at, scrape_days_since, scrape_stale}` |
| base_demand 实际周需求 | `app.utils.forecast_data.base_demand_view(barcode, end_date, weeks, session)` | `{sku_type, series: dict[date,int]|None, ...}`；series key 为周一 `date` |
| 下期预测 p50 | `app.models.ForecastOutput`（表 `forecast_output`），列 `product_barcode/p50/p98/sku_type` | 最新快照；按 `sku_type in (retail_dominant, mixed)` 求和 |
| 模型校准 bias | `app.models.BacktestRun`(id) + `BacktestResult`(run_id, bias) | `bias = mean(predicted - actual)`；>0=预测整体偏高 |
| skip 抑制集 | `app.services.restock_decisions.list_suppressed(session)` | `{barcode: {skipped_at, reason, days_left}}` |
| 采购订单列表 | `app.services.purchase.list_orders(limit)` | `[{id, supplier_id, supplier_name, order_date, arrival_date, status, ...}]`；status ∈ placed/arrived/void |
| 供应商前置期 | `app.services.purchase.compute_supplier_lead_times()` | `[{supplier_id, supplier_name, median_days, ...}]` |
| 数据异常 | `app.services.data_quality.build_report()` | `{<anomaly_key>: {count, samples}, ...}` |
| DB session | `app.repositories.stockpile_db._session()`（context manager） | — |
| 当日 | `app.services.analytics._shared._today()` / `_parse_date(str)` | — |

约定：所有 compute 函数接受显式 `as_of: date` 参数（默认 `_today()`），便于测试注入固定日期；**绝不**对真实库跑测试（conftest 临时 sqlite，见 spec §8）。

---

## File Structure

- **Create** `app/services/briefing.py` — 聚合编排：`compute_data_week()`、5 个 `compute_*_card()`、3 个 `build_*_actions()`、`build_briefing()`。
- **Create** `app/routes/briefing.py` — `briefing` 蓝图：`GET /briefing`、`GET /briefing/data`。
- **Modify** `app/routes/__init__.py` — import + 注册 `briefing_bp`（置于 dashboard 之后，保持默认落页不变）。
- **Create** `templates/partials/_page_briefing.html` — 卡片 + 行动列表骨架（Alpine）。
- **Modify** `templates/index.html` — include partial + 脚本引入。
- **Modify** `static/js/store.js` — nav `pages` 数组**置顶**加 `briefing` 项。
- **Create** `static/js/briefing.js` — `onFirstActivate("briefing", …)` 拉 `/briefing/data` 填充。
- **Create** `tests/test_briefing_service.py` — 全部口径 + 降级 + 错误隔离单测。
- **Create** `tests/test_briefing_routes.py` — 路由烟雾 + 系统级失败码。

常量（置于 `briefing.py` 顶部）：
```python
URGENT_COVER_WEEKS = 2.0       # 可售周数 ≤ 此值算「紧急」补货
SALES_MIN_COVER_SKUS = 5       # base_demand 覆盖 SKU < 此值 → 销售口径覆盖不足
ACTION_LIST_LIMIT = 5          # 每个行动列表默认条数
DYING_CATEGORIES = ("declining", "dying")  # 压货风险纳入的生命周期类
```

---

## Task 1: 数据周选取纯函数 `compute_data_week`

**Files:**
- Create: `app/services/briefing.py`
- Test: `tests/test_briefing_service.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_briefing_service.py
from datetime import date

from app.services import briefing


def test_data_week_uses_latest_complete_week():
    # 2026-06-08 是周一; 该周到 06-14 才完整, 最新事件停在 06-10(周三) → 退上一完整周 06-01
    dw, complete = briefing.compute_data_week(date(2026, 6, 10))
    assert dw == date(2026, 6, 1)
    assert complete is True


def test_data_week_latest_week_complete_when_data_runs_to_sunday():
    # 最新事件到 06-07(周日), 则 06-01 当周完整, 用 06-01
    dw, complete = briefing.compute_data_week(date(2026, 6, 7))
    assert dw == date(2026, 6, 1)
    assert complete is True


def test_data_week_none_when_no_events():
    dw, complete = briefing.compute_data_week(None)
    assert dw is None
    assert complete is False
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_briefing_service.py -k data_week -v`
Expected: FAIL（`module 'app.services.briefing' has no attribute 'compute_data_week'` 或 ImportError）

- [ ] **Step 3: 写最小实现**

```python
# app/services/briefing.py
"""最新批次简报 (老板 backlog #3) 聚合编排。

只读聚合现有物化表/服务, 不建表不加 cron。每个 card/action 独立降级。
口径见 docs/superpowers/specs/2026-06-09-morning-briefing-design.md。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

URGENT_COVER_WEEKS = 2.0
SALES_MIN_COVER_SKUS = 5
ACTION_LIST_LIMIT = 5
DYING_CATEGORIES = ("declining", "dying")


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def compute_data_week(latest_event_date: date | None) -> tuple[date | None, bool]:
    """本批次数据周 = 最新的「完整 ISO 周」的周一。

    完整周定义: week_monday + 6 天 <= latest_event_date (整周已落数据)。
    最新周不完整 → 退上一完整周。无事件 → (None, False)。
    """
    if latest_event_date is None:
        return None, False
    candidate = _monday(latest_event_date)
    if candidate + timedelta(days=6) <= latest_event_date:
        return candidate, True
    return candidate - timedelta(days=7), True
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_briefing_service.py -k data_week -v`
Expected: PASS（3 个）

- [ ] **Step 5: 提交**

```bash
git add app/services/briefing.py tests/test_briefing_service.py
git commit -m "feat(briefing): 数据周选取纯函数(最新完整ISO周)"
```

---

## Task 2: 销售健康卡 `compute_sales_health`

**口径**：本批次完整周 base_demand Σ vs 上一完整周 Σ（涨跌量+%）；副信息=下期预测 p50 Σ、模型校准 bias。仅 retail_dominant/mixed 且有 forecast 覆盖的 SKU 集合。降级：覆盖<5、上周无数据、bias 无数据。**禁止** actual vs forecast_p50 偏差结论。

**Files:**
- Modify: `app/services/briefing.py`
- Test: `tests/test_briefing_service.py`

- [ ] **Step 1: 写失败测试**

```python
def test_sales_health_normal(monkeypatch):
    # 覆盖 6 个 SKU, 本周 base_demand Σ=120, 上周 Σ=96 → +25%
    monkeypatch.setattr(briefing, "_forecast_covered_barcodes",
                        lambda s: ["b1", "b2", "b3", "b4", "b5", "b6"])
    monkeypatch.setattr(briefing, "_forecast_p50_sum", lambda s: 380.0)
    monkeypatch.setattr(briefing, "_latest_backtest_bias", lambda s: 0.06)

    def fake_bd(barcode, end_date, weeks, session):
        cur = date(2026, 6, 1)
        prev = date(2026, 5, 25)
        return {"series": {cur: 20, prev: 16}, "sku_type": "retail_dominant"}
    monkeypatch.setattr(briefing, "_base_demand_view", fake_bd)

    card = briefing.compute_sales_health(
        session=None, data_week=date(2026, 6, 1), data_week_complete=True)
    assert card["ok"] is True
    assert card["covered_skus"] == 6
    assert card["current_qty"] == 120      # 6 × 20
    assert card["previous_qty"] == 96      # 6 × 16
    assert card["delta_pct"] == 25.0
    assert card["forecast_next_p50"] == 380.0
    assert card["model_bias_pct"] == 6.0   # 0.06 → 6%(整体偏高)


def test_sales_health_coverage_insufficient(monkeypatch):
    monkeypatch.setattr(briefing, "_forecast_covered_barcodes", lambda s: ["b1", "b2"])
    monkeypatch.setattr(briefing, "_forecast_p50_sum", lambda s: 0.0)
    monkeypatch.setattr(briefing, "_latest_backtest_bias", lambda s: None)
    monkeypatch.setattr(briefing, "_base_demand_view",
                        lambda *a, **k: {"series": {date(2026, 6, 1): 5}, "sku_type": "mixed"})
    card = briefing.compute_sales_health(
        session=None, data_week=date(2026, 6, 1), data_week_complete=True)
    assert card["ok"] is True
    assert card["status"] == "coverage_insufficient"
    assert card["delta_pct"] is None


def test_sales_health_no_data_week(monkeypatch):
    card = briefing.compute_sales_health(
        session=None, data_week=None, data_week_complete=False)
    assert card["status"] == "week_incomplete"
    assert card["delta_pct"] is None
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_briefing_service.py -k sales_health -v`
Expected: FAIL（`compute_sales_health` 不存在）

- [ ] **Step 3: 写实现**（加到 `briefing.py`）

```python
def _forecast_covered_barcodes(session) -> list[str]:
    """有 forecast 且 sku_type ∈ retail_dominant/mixed 的 barcode 集合。"""
    from sqlalchemy import select

    from app.models import ForecastOutput

    rows = session.execute(
        select(ForecastOutput.product_barcode).where(
            ForecastOutput.sku_type.in_(("retail_dominant", "mixed"))
        )
    ).scalars().all()
    return list(rows)


def _forecast_p50_sum(session) -> float:
    from sqlalchemy import func, select

    from app.models import ForecastOutput

    total = session.execute(
        select(func.coalesce(func.sum(ForecastOutput.p50), 0.0)).where(
            ForecastOutput.sku_type.in_(("retail_dominant", "mixed"))
        )
    ).scalar()
    return float(total or 0.0)


def _latest_backtest_bias(session) -> float | None:
    """最新 backtest run 的平均 bias(=mean(pred-actual)); 无数据返回 None。"""
    from sqlalchemy import func, select

    from app.models import BacktestResult, BacktestRun

    run_id = session.execute(select(func.max(BacktestRun.id))).scalar()
    if run_id is None:
        return None
    avg = session.execute(
        select(func.avg(BacktestResult.bias)).where(BacktestResult.run_id == run_id)
    ).scalar()
    return float(avg) if avg is not None else None


def _base_demand_view(barcode, end_date, weeks, session):
    """薄包装, 便于测试 monkeypatch。"""
    from app.utils.forecast_data import base_demand_view

    return base_demand_view(barcode, end_date, weeks, session)


def compute_sales_health(session, data_week, data_week_complete) -> dict[str, Any]:
    if data_week is None or not data_week_complete:
        return {"ok": True, "status": "week_incomplete", "delta_pct": None,
                "current_qty": None, "previous_qty": None,
                "forecast_next_p50": None, "model_bias_pct": None, "covered_skus": 0}

    prev_week = data_week - timedelta(days=7)
    barcodes = _forecast_covered_barcodes(session)
    cur_sum = 0
    prev_sum = 0
    covered = 0
    for bc in barcodes:
        bd = _base_demand_view(bc, data_week, 2, session)
        series = bd.get("series") or {}
        if data_week in series:
            covered += 1
            cur_sum += int(series.get(data_week, 0))
            prev_sum += int(series.get(prev_week, 0))

    forecast_next = _forecast_p50_sum(session)
    bias = _latest_backtest_bias(session)
    model_bias_pct = round(bias * 100.0, 1) if bias is not None else None

    if covered < SALES_MIN_COVER_SKUS:
        return {"ok": True, "status": "coverage_insufficient", "delta_pct": None,
                "current_qty": cur_sum, "previous_qty": None,
                "forecast_next_p50": forecast_next, "model_bias_pct": model_bias_pct,
                "covered_skus": covered}

    if prev_sum <= 0:
        return {"ok": True, "status": "no_previous_week", "delta_pct": None,
                "current_qty": cur_sum, "previous_qty": prev_sum,
                "forecast_next_p50": forecast_next, "model_bias_pct": model_bias_pct,
                "covered_skus": covered}

    delta_pct = round((cur_sum - prev_sum) / prev_sum * 100.0, 1)
    return {"ok": True, "status": "ok", "delta_pct": delta_pct,
            "current_qty": cur_sum, "previous_qty": prev_sum,
            "forecast_next_p50": forecast_next, "model_bias_pct": model_bias_pct,
            "covered_skus": covered}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_briefing_service.py -k sales_health -v`
Expected: PASS（3 个）

- [ ] **Step 5: 提交**

```bash
git add app/services/briefing.py tests/test_briefing_service.py
git commit -m "feat(briefing): 销售健康卡(base_demand环比+预测/校准旁注)"
```

---

## Task 3: 补货风险卡 + 建议补货列表

**口径**：卡=未抑制且 `restock_qty_p50>0` 的 SKU 数，拆紧急(`weeks_of_cover ≤ 2`)/一般。列表=同集合按可售周数升序（None 视为很大排后），平手按建议量降序，Top 5。

**Files:**
- Modify: `app/services/briefing.py`
- Test: `tests/test_briefing_service.py`

- [ ] **Step 1: 写失败测试**

```python
def _row(bc, **kw):
    base = {"barcode": bc, "model": bc.upper(), "qty_total": 10,
            "weekly_velocity": 2.0, "weeks_of_cover": 5.0,
            "restock_qty_p50": 6, "stockout_zero_weeks_last8": 0,
            "auto_category": "stable", "manual_category": None,
            "inventory_cost_value_eur": None}
    base.update(kw)
    return base


def test_restock_risk_counts_and_urgent(monkeypatch):
    rows = [_row("a", weeks_of_cover=1.0), _row("b", weeks_of_cover=8.0),
            _row("c", restock_qty_p50=0), _row("d", weeks_of_cover=None)]
    monkeypatch.setattr(briefing, "_suppressed_barcodes", lambda s: set())
    card = briefing.compute_restock_risk(session=None, rows=rows)
    assert card["ok"] is True
    assert card["total"] == 3        # a,b,d (c 的 p50=0 排除)
    assert card["urgent"] == 1       # 仅 a (cover 1.0 ≤ 2)


def test_restock_risk_excludes_suppressed(monkeypatch):
    rows = [_row("a"), _row("b")]
    monkeypatch.setattr(briefing, "_suppressed_barcodes", lambda s: {"a"})
    card = briefing.compute_restock_risk(session=None, rows=rows)
    assert card["total"] == 1


def test_restock_actions_sorted(monkeypatch):
    rows = [_row("a", weeks_of_cover=5.0, restock_qty_p50=6),
            _row("b", weeks_of_cover=1.0, restock_qty_p50=9),
            _row("d", weeks_of_cover=None, restock_qty_p50=20)]
    monkeypatch.setattr(briefing, "_suppressed_barcodes", lambda s: set())
    out = briefing.build_restock_actions(session=None, rows=rows)
    assert out["ok"] is True
    assert [i["barcode"] for i in out["items"]] == ["b", "a", "d"]  # cover 升序, None 最后
    assert out["total"] == 3
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_briefing_service.py -k restock -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

```python
def _suppressed_barcodes(session) -> set[str]:
    from app.services.restock_decisions import list_suppressed

    return set(list_suppressed(session).keys())


def _restock_candidates(session, rows) -> list[dict[str, Any]]:
    suppressed = _suppressed_barcodes(session)
    return [
        r for r in rows
        if (r.get("restock_qty_p50") or 0) > 0 and r["barcode"] not in suppressed
    ]


def compute_restock_risk(session, rows) -> dict[str, Any]:
    cands = _restock_candidates(session, rows)
    urgent = sum(
        1 for r in cands
        if r.get("weeks_of_cover") is not None and r["weeks_of_cover"] <= URGENT_COVER_WEEKS
    )
    return {"ok": True, "total": len(cands), "urgent": urgent}


def _cover_sort_key(r) -> float:
    c = r.get("weeks_of_cover")
    return c if c is not None else float("inf")


def build_restock_actions(session, rows) -> dict[str, Any]:
    cands = _restock_candidates(session, rows)
    cands.sort(key=lambda r: (_cover_sort_key(r), -(r.get("restock_qty_p50") or 0)))
    items = [
        {"barcode": r["barcode"], "model": r.get("model"),
         "qty_total": r.get("qty_total"), "weekly_velocity": r.get("weekly_velocity"),
         "restock_qty_p50": r.get("restock_qty_p50"), "weeks_of_cover": r.get("weeks_of_cover")}
        for r in cands[:ACTION_LIST_LIMIT]
    ]
    return {"ok": True, "items": items, "total": len(cands)}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_briefing_service.py -k restock -v`
Expected: PASS（3 个）

- [ ] **Step 5: 提交**

```bash
git add app/services/briefing.py tests/test_briefing_service.py
git commit -m "feat(briefing): 补货风险卡+建议补货列表(扣skip抑制,可售周数排序)"
```

---

## Task 4: 疑似缺货影响卡 `compute_stockout_impact`

**口径**：`stockout_zero_weeks_last8 > 0` 的 SKU 数 + Top 清单（按 zero_weeks 降序）。不估损失量。

**Files:**
- Modify: `app/services/briefing.py`
- Test: `tests/test_briefing_service.py`

- [ ] **Step 1: 写失败测试**

```python
def test_stockout_impact(monkeypatch):
    rows = [_row("a", stockout_zero_weeks_last8=3),
            _row("b", stockout_zero_weeks_last8=0),
            _row("c", stockout_zero_weeks_last8=5)]
    card = briefing.compute_stockout_impact(rows=rows)
    assert card["ok"] is True
    assert card["total"] == 2
    assert [i["barcode"] for i in card["samples"]] == ["c", "a"]  # zero_weeks 降序
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_briefing_service.py -k stockout_impact -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

```python
def compute_stockout_impact(rows) -> dict[str, Any]:
    hits = [r for r in rows if (r.get("stockout_zero_weeks_last8") or 0) > 0]
    hits.sort(key=lambda r: r.get("stockout_zero_weeks_last8") or 0, reverse=True)
    samples = [
        {"barcode": r["barcode"], "model": r.get("model"),
         "zero_weeks": r.get("stockout_zero_weeks_last8"), "qty_total": r.get("qty_total")}
        for r in hits[:ACTION_LIST_LIMIT]
    ]
    return {"ok": True, "total": len(hits), "samples": samples}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_briefing_service.py -k stockout_impact -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/briefing.py tests/test_briefing_service.py
git commit -m "feat(briefing): 疑似缺货影响卡(缺货零销SKU数+清单)"
```

---

## Task 5: 压货风险卡 `compute_overstock_risk`（成本优雅降级）

**口径**：`auto/manual_category ∈ (declining, dying)` 且 `qty_total > 0` 的 SKU 数 + 库存量合计；成本可用→加显压货金额 Σ(`inventory_cost_value_eur`)。全空→`cost_available=false` 只显数量。

**Files:**
- Modify: `app/services/briefing.py`
- Test: `tests/test_briefing_service.py`

- [ ] **Step 1: 写失败测试**

```python
def test_overstock_with_cost():
    rows = [_row("a", auto_category="dying", qty_total=10, inventory_cost_value_eur=100.0),
            _row("b", auto_category="declining", qty_total=5, inventory_cost_value_eur=50.0),
            _row("c", auto_category="stable", qty_total=99, inventory_cost_value_eur=999.0)]
    card = briefing.compute_overstock_risk(rows=rows)
    assert card["ok"] is True
    assert card["total"] == 2
    assert card["stock_qty"] == 15
    assert card["cost_available"] is True
    assert card["overstock_value_eur"] == 150.0


def test_overstock_cost_all_empty():
    rows = [_row("a", auto_category="dying", qty_total=10, inventory_cost_value_eur=None),
            _row("b", manual_category="declining", qty_total=5, inventory_cost_value_eur=None)]
    card = briefing.compute_overstock_risk(rows=rows)
    assert card["total"] == 2
    assert card["stock_qty"] == 15
    assert card["cost_available"] is False
    assert card["overstock_value_eur"] is None
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_briefing_service.py -k overstock -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

```python
def _is_dying(r) -> bool:
    cat = r.get("manual_category") or r.get("auto_category")
    return cat in DYING_CATEGORIES


def compute_overstock_risk(rows) -> dict[str, Any]:
    hits = [r for r in rows if _is_dying(r) and (r.get("qty_total") or 0) > 0]
    stock_qty = sum(int(r.get("qty_total") or 0) for r in hits)
    costs = [r.get("inventory_cost_value_eur") for r in hits
             if r.get("inventory_cost_value_eur") is not None]
    cost_available = len(costs) > 0
    overstock_value = round(sum(costs), 2) if cost_available else None
    hits.sort(key=lambda r: int(r.get("qty_total") or 0), reverse=True)
    samples = [
        {"barcode": r["barcode"], "model": r.get("model"),
         "qty_total": r.get("qty_total"),
         "cost_value_eur": r.get("inventory_cost_value_eur")}
        for r in hits[:ACTION_LIST_LIMIT]
    ]
    return {"ok": True, "total": len(hits), "stock_qty": stock_qty,
            "cost_available": cost_available, "overstock_value_eur": overstock_value,
            "samples": samples}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_briefing_service.py -k overstock -v`
Expected: PASS（2 个）

- [ ] **Step 5: 提交**

```bash
git add app/services/briefing.py tests/test_briefing_service.py
git commit -m "feat(briefing): 压货风险卡(滞销SKU数+库存量, 成本优雅降级)"
```

---

## Task 6: 数据新鲜度卡 `compute_data_health`（含成本覆盖率）

**口径**：复用 `get_data_freshness()`，加显成本覆盖率%（分母=`list_sku_summary` 全部 SKU 数；分子=`inventory_cost_value_eur` 非空数）。

**Files:**
- Modify: `app/services/briefing.py`
- Test: `tests/test_briefing_service.py`

- [ ] **Step 1: 写失败测试**

```python
def test_data_health_cost_coverage(monkeypatch):
    rows = [_row("a", inventory_cost_value_eur=10.0),
            _row("b", inventory_cost_value_eur=None),
            _row("c", inventory_cost_value_eur=20.0),
            _row("d", inventory_cost_value_eur=None)]
    monkeypatch.setattr(briefing, "_freshness",
                        lambda: {"last_import_date": "2026-06-08", "days_since": 1, "stale": False})
    card = briefing.compute_data_health(rows=rows)
    assert card["ok"] is True
    assert card["stale"] is False
    assert card["cost_coverage_pct"] == 50.0   # 2/4


def test_data_health_empty_rows(monkeypatch):
    monkeypatch.setattr(briefing, "_freshness",
                        lambda: {"last_import_date": None, "days_since": None, "stale": False})
    card = briefing.compute_data_health(rows=[])
    assert card["cost_coverage_pct"] is None
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_briefing_service.py -k data_health -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

```python
def _freshness() -> dict[str, Any]:
    from app.services.analytics.freshness import get_data_freshness

    return get_data_freshness()


def compute_data_health(rows) -> dict[str, Any]:
    f = _freshness()
    total = len(rows)
    with_cost = sum(1 for r in rows if r.get("inventory_cost_value_eur") is not None)
    coverage = round(with_cost * 100.0 / total, 1) if total else None
    return {"ok": True,
            "last_import_date": f.get("last_import_date"),
            "days_since": f.get("days_since"),
            "stale": f.get("stale"),
            "scrape_stale": f.get("scrape_stale"),
            "cost_coverage_pct": coverage}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_briefing_service.py -k data_health -v`
Expected: PASS（2 个）

- [ ] **Step 5: 提交**

```bash
git add app/services/briefing.py tests/test_briefing_service.py
git commit -m "feat(briefing): 数据新鲜度卡(复用freshness+成本覆盖率)"
```

---

## Task 7: 建议催/确认列表 `build_follow_up_actions`

**口径**：`list_orders()` 中 `status=='placed'` 的订单；逾期天数 = `as_of - (order_date + 供应商中位前置期)`，无前置期数据则逾期天数 None、回退按 order_date 升序（最久最前）。按逾期天数降序 Top 5。空表→`status='empty'`。

**Files:**
- Modify: `app/services/briefing.py`
- Test: `tests/test_briefing_service.py`

- [ ] **Step 1: 写失败测试**

```python
def test_follow_up_overdue_sort(monkeypatch):
    orders = [
        {"id": 1, "supplier_id": "S1", "supplier_name": "供应商1",
         "order_date": "2026-05-01", "status": "placed", "total_qty": 100},
        {"id": 2, "supplier_id": "S2", "supplier_name": "供应商2",
         "order_date": "2026-06-01", "status": "placed", "total_qty": 50},
        {"id": 3, "supplier_id": "S1", "supplier_name": "供应商1",
         "order_date": "2026-05-20", "status": "arrived", "total_qty": 10},
    ]
    monkeypatch.setattr(briefing, "_list_orders", lambda: orders)
    monkeypatch.setattr(briefing, "_supplier_lead_days",
                        lambda: {"S1": 10, "S2": 10})
    out = briefing.build_follow_up_actions(as_of=date(2026, 6, 9))
    assert out["ok"] is True
    assert out["total"] == 2                       # 仅 placed
    # 订单1: 05-01+10=05-11, 逾期 29 天; 订单2: 06-01+10=06-11, 逾期 -2(未到期)
    assert out["items"][0]["id"] == 1
    assert out["items"][0]["overdue_days"] == 29


def test_follow_up_no_lead_time_fallback(monkeypatch):
    orders = [
        {"id": 1, "supplier_id": "S9", "supplier_name": "X",
         "order_date": "2026-06-01", "status": "placed", "total_qty": 5},
        {"id": 2, "supplier_id": "S9", "supplier_name": "X",
         "order_date": "2026-05-01", "status": "placed", "total_qty": 7},
    ]
    monkeypatch.setattr(briefing, "_list_orders", lambda: orders)
    monkeypatch.setattr(briefing, "_supplier_lead_days", lambda: {})
    out = briefing.build_follow_up_actions(as_of=date(2026, 6, 9))
    assert out["items"][0]["id"] == 2              # 无前置期 → order_date 升序
    assert out["items"][0]["overdue_days"] is None


def test_follow_up_empty(monkeypatch):
    monkeypatch.setattr(briefing, "_list_orders", lambda: [])
    monkeypatch.setattr(briefing, "_supplier_lead_days", lambda: {})
    out = briefing.build_follow_up_actions(as_of=date(2026, 6, 9))
    assert out["ok"] is True
    assert out["status"] == "empty"
    assert out["items"] == []
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_briefing_service.py -k follow_up -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

```python
def _list_orders():
    from app.services.purchase import list_orders

    return list_orders(limit=500)


def _supplier_lead_days() -> dict[str, float]:
    from app.services.purchase import compute_supplier_lead_times

    return {r["supplier_id"]: r["median_days"] for r in compute_supplier_lead_times()}


def build_follow_up_actions(as_of: date) -> dict[str, Any]:
    from datetime import date as date_cls

    orders = [o for o in _list_orders() if o.get("status") == "placed"]
    if not orders:
        return {"ok": True, "status": "empty", "items": [], "total": 0}

    lead = _supplier_lead_days()
    enriched = []
    for o in orders:
        overdue = None
        try:
            od = date_cls.fromisoformat(o["order_date"])
        except (ValueError, TypeError, KeyError):
            od = None
        md = lead.get(o.get("supplier_id"))
        if od is not None and md is not None:
            overdue = (as_of - (od + timedelta(days=int(md)))).days
        enriched.append({"id": o["id"], "supplier_name": o.get("supplier_name"),
                         "supplier_id": o.get("supplier_id"), "order_date": o.get("order_date"),
                         "total_qty": o.get("total_qty"), "overdue_days": overdue,
                         "_od": od or date_cls.max})
    # 有逾期天数的按逾期降序在前; 无的按 order_date 升序在后
    enriched.sort(key=lambda e: (e["overdue_days"] is None,
                                 -(e["overdue_days"] or 0), e["_od"]))
    for e in enriched:
        e.pop("_od", None)
    return {"ok": True, "status": "ok", "items": enriched[:ACTION_LIST_LIMIT],
            "total": len(enriched)}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_briefing_service.py -k follow_up -v`
Expected: PASS（3 个）

- [ ] **Step 5: 提交**

```bash
git add app/services/briefing.py tests/test_briefing_service.py
git commit -m "feat(briefing): 建议催/确认列表(采购pending+前置期推算逾期)"
```

---

## Task 8: 建议复查异常列表 `build_review_actions`

**口径**：`build_report()` 各异常类 `{count}` 按 count 降序，count>0 的取 Top 5；每项带 ≤2 个 sample 摘要。忽略非异常块（如 `scanned_count` 这类 int 值）。

**Files:**
- Modify: `app/services/briefing.py`
- Test: `tests/test_briefing_service.py`

- [ ] **Step 1: 写失败测试**

```python
def test_review_actions_sorted(monkeypatch):
    report = {
        "negative_stock": {"count": 12, "samples": [{"product_barcode": "x"}]},
        "unknown_prefix": {"count": 0, "samples": []},
        "flippers": {"count": 5, "samples": []},
        "scanned_count": 999,   # 非异常块(int), 须被忽略
    }
    monkeypatch.setattr(briefing, "_quality_report", lambda: report)
    out = briefing.build_review_actions()
    assert out["ok"] is True
    assert [i["kind"] for i in out["items"]] == ["negative_stock", "flippers"]
    assert out["items"][0]["count"] == 12
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_briefing_service.py -k review_actions -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

```python
def _quality_report() -> dict[str, Any]:
    from app.services.data_quality import build_report

    return build_report()


def build_review_actions() -> dict[str, Any]:
    report = _quality_report()
    blocks = [
        {"kind": k, "count": v["count"], "samples": (v.get("samples") or [])[:2]}
        for k, v in report.items()
        if isinstance(v, dict) and "count" in v and (v.get("count") or 0) > 0
    ]
    blocks.sort(key=lambda b: b["count"], reverse=True)
    return {"ok": True, "items": blocks[:ACTION_LIST_LIMIT],
            "total": len(blocks)}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_briefing_service.py -k review_actions -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/briefing.py tests/test_briefing_service.py
git commit -m "feat(briefing): 建议复查异常列表(data_quality按数量排序)"
```

---

## Task 9: 聚合编排 `build_briefing`（每块独立 try）

**口径**：拉一次 `list_sku_summary()` 复用给各卡片；每个 card/action 包 try，失败→该块 `{ok:false, error}`，不拖垮整页。顶层返回 `ok/generated_at/data_week/data_week_complete/cards/actions`。

**Files:**
- Modify: `app/services/briefing.py`
- Test: `tests/test_briefing_service.py`

- [ ] **Step 1: 写失败测试**

```python
def test_build_briefing_isolates_block_failure(monkeypatch):
    monkeypatch.setattr(briefing, "_load_rows", lambda: [_row("a", stockout_zero_weeks_last8=2)])
    monkeypatch.setattr(briefing, "_latest_event_date", lambda: date(2026, 6, 10))
    # 让销售健康抛错, 验证其余块仍 ok
    def boom(*a, **k):
        raise RuntimeError("forecast table missing")
    monkeypatch.setattr(briefing, "compute_sales_health", boom)
    monkeypatch.setattr(briefing, "_suppressed_barcodes", lambda s: set())
    monkeypatch.setattr(briefing, "_freshness",
                        lambda: {"last_import_date": "2026-06-08", "days_since": 1, "stale": False})
    monkeypatch.setattr(briefing, "_list_orders", lambda: [])
    monkeypatch.setattr(briefing, "_supplier_lead_days", lambda: {})
    monkeypatch.setattr(briefing, "_quality_report", lambda: {})

    out = briefing.build_briefing(as_of=date(2026, 6, 9), generated_at="2026-06-09T13:40:00")
    assert out["ok"] is True
    assert out["cards"]["sales_health"]["ok"] is False
    assert "error" in out["cards"]["sales_health"]
    assert out["cards"]["stockout_impact"]["ok"] is True   # 其余块不受影响
    assert out["cards"]["stockout_impact"]["total"] == 1
    assert out["data_week"] == "2026-06-01"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_briefing_service.py -k build_briefing -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

```python
def _latest_event_date() -> date | None:
    from sqlalchemy import func, select

    from app.models import InventoryEvent
    from app.repositories import stockpile_db
    from app.services.analytics._shared import _parse_date

    with stockpile_db._session() as session:
        val = session.execute(
            select(func.max(InventoryEvent.event_at)).where(InventoryEvent.event_type == "sale")
        ).scalar()
    return _parse_date(str(val)) if val else None


def _load_rows() -> list[dict[str, Any]]:
    from app.services.analytics.summary import list_sku_summary

    return list_sku_summary()


def _safe(fn) -> dict[str, Any]:
    """运行一个 block 函数, 任何业务异常 → {ok:false, error}。系统级异常由上层处理。"""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — 业务块隔离, 不吞系统级(见路由层)
        return {"ok": False, "error": str(exc)}


def build_briefing(as_of: date, generated_at: str) -> dict[str, Any]:
    from app.repositories import stockpile_db

    rows = _load_rows()
    latest = _latest_event_date()
    data_week, complete = compute_data_week(latest)

    with stockpile_db._session() as session:
        cards = {
            "sales_health": _safe(
                lambda: compute_sales_health(session, data_week, complete)),
            "restock_risk": _safe(lambda: compute_restock_risk(session, rows)),
            "stockout_impact": _safe(lambda: compute_stockout_impact(rows)),
            "overstock_risk": _safe(lambda: compute_overstock_risk(rows)),
            "data_health": _safe(lambda: compute_data_health(rows)),
        }
        actions = {
            "restock": _safe(lambda: build_restock_actions(session, rows)),
            "follow_up": _safe(lambda: build_follow_up_actions(as_of)),
            "review_anomalies": _safe(build_review_actions),
        }

    return {"ok": True, "generated_at": generated_at,
            "data_week": data_week.isoformat() if data_week else None,
            "data_week_complete": complete, "cards": cards, "actions": actions}
```

- [ ] **Step 4: 运行确认通过 + 全文件**

Run: `pytest tests/test_briefing_service.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/briefing.py tests/test_briefing_service.py
git commit -m "feat(briefing): 聚合编排build_briefing(每块独立try隔离)"
```

---

## Task 10: 路由蓝图 `app/routes/briefing.py` + 注册

**口径**：`GET /briefing` 渲染页面（复用 index.html shell，前端按 nav 切页）；`GET /briefing/data` 返回 `build_briefing()` JSON。业务块失败已在 service 内吞为 `ok=false`；系统级失败（如 DB 连不上）让异常冒泡 → Flask 500。

**Files:**
- Create: `app/routes/briefing.py`
- Modify: `app/routes/__init__.py`
- Test: `tests/test_briefing_routes.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_briefing_routes.py
def test_briefing_data_ok(client):
    resp = client.get("/briefing/data")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "cards" in data and "actions" in data
    assert set(data["cards"]) == {
        "sales_health", "restock_risk", "stockout_impact", "overstock_risk", "data_health"}
    assert set(data["actions"]) == {"restock", "follow_up", "review_anomalies"}


def test_briefing_data_system_failure_returns_500(client, monkeypatch):
    from app.services import briefing
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(briefing, "build_briefing", boom)
    resp = client.get("/briefing/data")
    assert resp.status_code == 500
```

> `client` fixture：复用现有 `tests/conftest.py` 的测试 client（临时 sqlite，已注册全部蓝图）。若 conftest 暂无该 fixture，参照现有路由测试（如 `tests/test_*` 中已有的 Flask client fixture）同款命名。

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_briefing_routes.py -v`
Expected: FAIL（404，蓝图未注册）

- [ ] **Step 3: 写实现**

```python
# app/routes/briefing.py
"""最新批次简报 (老板 backlog #3) 路由。只读, 走 session auth。"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, render_template

from app.services import briefing as briefing_service
from app.services.analytics._shared import _today

bp = Blueprint("briefing", __name__, url_prefix="/briefing")


@bp.get("")
def page():
    return render_template("index.html")


@bp.get("/data")
def data():
    # 系统级异常(DB/schema)不在此吞: 让其冒泡 → Flask 500, 不伪装 200。
    payload = briefing_service.build_briefing(
        as_of=_today(),
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )
    return jsonify(payload)
```

> 注：`render_template("index.html")` 与其他页面蓝图一致（单页 shell + 前端切页）。若现有页面路由用了特定上下文（如 `current_user`），照 `app/routes/dashboard.py` 的 `page()` 同款补齐参数。

在 `app/routes/__init__.py` 注册（dashboard 之后，保持默认落页不变）：

```python
# import 区(按字母序插入, analytics 之后/attendance 之前 → 实际 briefing 在 analytics 前):
from app.routes.briefing import bp as briefing_bp
# register_routes() 内, app.register_blueprint(dashboard_bp) 之后一行:
    app.register_blueprint(briefing_bp)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_briefing_routes.py -v`
Expected: PASS（2 个）

- [ ] **Step 5: 提交**

```bash
git add app/routes/briefing.py app/routes/__init__.py tests/test_briefing_routes.py
git commit -m "feat(briefing): 路由蓝图(/briefing + /briefing/data)+注册"
```

---

## Task 11: 前端 — nav 置顶 + partial + 加载脚本

**Files:**
- Modify: `static/js/store.js`（nav `pages` 数组置顶）
- Modify: `templates/index.html`（include partial + 脚本引入）
- Create: `templates/partials/_page_briefing.html`
- Create: `static/js/briefing.js`

- [ ] **Step 1: nav 置顶加项**（`static/js/store.js`，`pages: [` 之后第一行插入）

```javascript
      { id: "briefing",          label: "最新批次简报", icon: "dashboard",  code: "★", shortcut: "" },
```

> 不改 `current` 默认值（仍是现有默认落页），满足验收 #8。

- [ ] **Step 2: index.html 挂载**（`{% include 'partials/_page_dashboard.html' %}` 上一行插入 include；并在页面底部脚本区加 briefing.js）

在 `templates/index.html` 第 181 行附近 `{% include 'partials/_page_dashboard.html' %}` 之前插入：

```jinja
{% include 'partials/_page_briefing.html' %}
```

并在页面底部脚本区（其他 `static/js/*.js` 引入处，如 `forecast_eval.js` 附近）加：

```html
<script src="{{ url_for('static', filename='js/briefing.js') }}" defer></script>
```

- [ ] **Step 3: partial 骨架**（`templates/partials/_page_briefing.html`）

```html
<div class="page" id="pageBriefing" x-data="briefingPage()"
     :class="$store.nav.current === 'briefing' ? 'active' : ''">
  <header class="briefing-head">
    <h2>最新批次简报</h2>
    <p class="briefing-sub" x-show="data">
      截至 <span x-text="data?.data_week || '—'"></span>
      · 刷新于 <span x-text="(data?.generated_at || '').replace('T',' ')"></span>
    </p>
    <p class="briefing-stale" x-show="data?.cards?.data_health?.stale"
       style="color:var(--danger)">
      数据已超过 <span x-text="data?.cards?.data_health?.days_since"></span> 天未刷新 ⚠
    </p>
  </header>

  <section class="briefing-cards">
    <!-- 销售健康 -->
    <article class="kpi-card">
      <div class="kpi-title">本批次销售健康</div>
      <template x-if="card('sales_health')?.ok && card('sales_health')?.status==='ok'">
        <div>
          <div class="kpi-value" x-text="(card('sales_health').delta_pct>=0?'+':'')
               + card('sales_health').delta_pct + '%'"></div>
          <div class="kpi-sub">较上批清洗后销量 ·
            下期系统预期约 <span x-text="Math.round(card('sales_health').forecast_next_p50)"></span> 件
            <template x-if="card('sales_health').model_bias_pct!==null">
              <span> · 模型近期校准：回测整体偏<span
                x-text="card('sales_health').model_bias_pct>=0?'高':'低'"></span>
                <span x-text="Math.abs(card('sales_health').model_bias_pct)"></span>%</span>
            </template>
          </div>
        </div>
      </template>
      <template x-if="card('sales_health')?.status==='coverage_insufficient'">
        <div class="kpi-sub">预测覆盖不足，暂不给销售结论</div>
      </template>
      <template x-if="card('sales_health')?.status==='no_previous_week'">
        <div class="kpi-sub">本批次销量 <span x-text="card('sales_health').current_qty"></span> 件（无上批可比）</div>
      </template>
      <template x-if="card('sales_health')?.status==='week_incomplete'">
        <div class="kpi-sub">数据周未完整</div>
      </template>
      <template x-if="card('sales_health') && !card('sales_health').ok">
        <div class="kpi-sub">暂不可用</div>
      </template>
    </article>

    <!-- 补货风险 -->
    <article class="kpi-card">
      <div class="kpi-title">当前补货风险</div>
      <template x-if="card('restock_risk')?.ok">
        <div>
          <div class="kpi-value" x-text="card('restock_risk').total"></div>
          <div class="kpi-sub">个 SKU 建议补货 · 紧急
            <span x-text="card('restock_risk').urgent"></span> 个（可售 ≤ 2 周）</div>
        </div>
      </template>
      <template x-if="card('restock_risk') && !card('restock_risk').ok">
        <div class="kpi-sub">暂不可用</div></template>
    </article>

    <!-- 疑似缺货影响 -->
    <article class="kpi-card">
      <div class="kpi-title">疑似缺货影响</div>
      <template x-if="card('stockout_impact')?.ok">
        <div>
          <div class="kpi-value" x-text="card('stockout_impact').total"></div>
          <div class="kpi-sub">个 SKU 近期零销疑因缺货，补货后或恢复</div>
        </div>
      </template>
      <template x-if="card('stockout_impact') && !card('stockout_impact').ok">
        <div class="kpi-sub">暂不可用</div></template>
    </article>

    <!-- 压货风险 -->
    <article class="kpi-card">
      <div class="kpi-title">当前压货风险</div>
      <template x-if="card('overstock_risk')?.ok">
        <div>
          <div class="kpi-value" x-text="card('overstock_risk').total"></div>
          <div class="kpi-sub">个滞销/呆滞 SKU 仍有库存（合计
            <span x-text="card('overstock_risk').stock_qty"></span> 件<template
              x-if="card('overstock_risk').cost_available">，约 €<span
              x-text="card('overstock_risk').overstock_value_eur"></span></template>）
            <template x-if="!card('overstock_risk').cost_available">
              <span style="color:var(--ink-3)"> · 无成本数据</span></template>
          </div>
        </div>
      </template>
      <template x-if="card('overstock_risk') && !card('overstock_risk').ok">
        <div class="kpi-sub">暂不可用</div></template>
    </article>

    <!-- 数据新鲜度 -->
    <article class="kpi-card">
      <div class="kpi-title">数据新鲜度</div>
      <template x-if="card('data_health')?.ok">
        <div>
          <div class="kpi-value" x-text="(card('data_health').days_since ?? '—') + ' 天前'"></div>
          <div class="kpi-sub">数据截止 <span x-text="card('data_health').last_import_date || '—'"></span>
            · 成本覆盖 <span x-text="card('data_health').cost_coverage_pct ?? '—'"></span>%</div>
        </div>
      </template>
      <template x-if="card('data_health') && !card('data_health').ok">
        <div class="kpi-sub">暂不可用</div></template>
    </article>
  </section>

  <section class="briefing-actions">
    <!-- 建议补货 -->
    <div class="action-list">
      <div class="action-head"><span>建议补货</span>
        <a href="/restock" class="action-all">查看全部 →</a></div>
      <template x-for="it in (action('restock')?.items || [])" :key="it.barcode">
        <div class="action-row">
          <span x-text="it.model || it.barcode"></span>
          <span>库存 <span x-text="it.qty_total"></span> · 周销 <span x-text="it.weekly_velocity"></span>
            · 建议 <span x-text="it.restock_qty_p50"></span>
            · 可售 <span x-text="it.weeks_of_cover ?? '—'"></span> 周</span>
        </div>
      </template>
      <div class="action-empty" x-show="(action('restock')?.items || []).length === 0">无</div>
    </div>

    <!-- 建议催/确认 -->
    <div class="action-list">
      <div class="action-head"><span>建议催/确认</span>
        <a href="/purchase" class="action-all">查看全部 →</a></div>
      <template x-if="action('follow_up')?.status === 'empty'">
        <div class="action-empty">暂无采购订单</div></template>
      <template x-for="it in (action('follow_up')?.items || [])" :key="it.id">
        <div class="action-row">
          <span x-text="it.supplier_name || it.supplier_id"></span>
          <span>数量 <span x-text="it.total_qty"></span> · 下单 <span x-text="it.order_date"></span>
            <template x-if="it.overdue_days !== null">
              · 逾期 <span x-text="it.overdue_days"></span> 天（按前置期推算）</template>
          </span>
        </div>
      </template>
    </div>

    <!-- 建议复查异常 -->
    <div class="action-list">
      <div class="action-head"><span>建议复查异常</span>
        <a href="/data_quality" class="action-all">查看全部 →</a></div>
      <template x-for="it in (action('review_anomalies')?.items || [])" :key="it.kind">
        <div class="action-row">
          <span x-text="it.kind"></span>
          <span x-text="it.count + ' 条'"></span>
        </div>
      </template>
      <div class="action-empty"
           x-show="(action('review_anomalies')?.items || []).length === 0">无异常</div>
    </div>
  </section>
</div>
```

- [ ] **Step 4: 加载脚本**（`static/js/briefing.js`）

```javascript
// 最新批次简报: 首次切到该页时拉 /briefing/data 填充。
function briefingPage() {
  return {
    data: null,
    card(key) { return this.data?.cards?.[key]; },
    action(key) { return this.data?.actions?.[key]; },
    init() {
      const store = window.Alpine?.store?.("nav");
      if (store) {
        store.onFirstActivate("briefing", () => this.load());
      } else {
        this.load();
      }
    },
    async load() {
      try {
        const resp = await fetch("/briefing/data");
        if (!resp.ok) { console.error("briefing data HTTP", resp.status); return; }
        this.data = await resp.json();
      } catch (e) {
        console.error("briefing load failed", e);
      }
    },
  };
}
window.briefingPage = briefingPage;
```

- [ ] **Step 5: 本地浏览器验证**（[[feedback_test_locally_before_push]] / [[feedback_local_dev_loop]]）

Run（开发服务器，热重载）：`./dev.ps1`（或 `python server.py`）
浏览器开 `http://127.0.0.1:5000` → 侧栏顶部点「最新批次简报」。
Expected：5 张卡片渲染（本地空成本 → 压货卡显「无成本数据」）；3 个列表渲染或显「无 / 暂无采购订单」；副标题显数据周；切页只触发一次 fetch（Network 面板确认）。

> ⚠️ 若前端不显示，先查 [[project_dev_server_zombie_port]]（:5000 僵尸进程）+ [[feedback_flask_template_cache]]（模板缓存需重启或开 `LABEL_SYNC_DEBUG=1`）。
> ⚠️ 本地 PG 若新功能撞 schema 缺列，照 [[project_local_alembic_2385c_missing_columns]] 手动补列。

- [ ] **Step 6: 提交**

```bash
git add static/js/store.js static/js/briefing.js templates/index.html templates/partials/_page_briefing.html
git commit -m "feat(briefing): 前端简报页(nav置顶+卡片+行动列表+懒加载)"
```

---

## Task 12: 全量验证 + e2e 烟雾

**Files:**
- Modify: `e2e/test_nav_lazy_load.py`（若以 page id 列表驱动，纳入 `briefing`；否则跳过）

- [ ] **Step 1: 全量单元 + 集成**

Run: `pytest tests/ -q`
Expected: 全绿（含新增 briefing 测试；原有 1018+ 不回归）

- [ ] **Step 2:（可选）e2e 切页烟雾**

若 `e2e/test_nav_lazy_load.py` 用 page id 列表驱动，确认 `briefing` 被纳入或显式加一条断言：切到 briefing → `#pageBriefing.active` 可见且 `/briefing/data` 被请求一次。
Run: `pytest e2e/test_nav_lazy_load.py -v`（opt-in，需 Playwright）

- [ ] **Step 3: 性能粗验**

开发服浏览器 Network：`/briefing/data` 响应时间 < 1s（复用 `list_sku_summary` 60s 缓存；首次冷算 ~2-3s 属已知，第二次应 <1s）。
> 若 `compute_sales_health` 的 base_demand 两周循环导致明显拖慢，按 spec §7：其 `_safe` 已天然隔离（单块失败/慢不拖累其余块的正确性）；如确认拖慢整页响应，可在该块外加超时保护或接受其 `ok=false` 降级，**不**回退整页。

- [ ] **Step 4: 收尾提交**

```bash
git add -A
git commit -m "test(briefing): e2e nav 烟雾纳入简报页 + 全量回归确认"
```

---

## Self-Review（plan 作者已核）

**Spec 覆盖：**
- §2 时间语义/完整周 → Task 1。
- §4 卡片 1-5 → Task 2/3/4/5/6（含覆盖不足、上周无数据、成本降级、成本覆盖率）。
- §5 三列表 + 排序 + 深链 + 采购空表降级 → Task 3/7/8 + Task 11 深链。
- §6 业务块 vs 系统级错误分层 → Task 9（`_safe` 隔离）+ Task 10（系统级冒泡 500，测试覆盖）。
- §7 性能/销售健康独立降级 → Task 12 Step 3 + Task 9 天然隔离。
- §8 测试（conftest 临时 sqlite，绝不碰真实库）→ 各 Task 测试 + 顶部约定。
- §9 验收 1-9 → Task 10/11/12 覆盖（页面/口径/列表/降级/错误/副标题/nav 置顶/全量绿）。

**占位扫描：** 无 TODO/TBD；每个代码步含完整代码。
**类型一致：** `compute_data_week` 返回 `(date|None, bool)` 全程一致；card 返回统一含 `ok`+`status`；action 返回统一 `ok/items/total`（follow_up 另带 `status`）。前端 `card()`/`action()` helper 键与 payload 一致。

**待执行者注意的真实不确定点（非占位，需现场对齐）：**
1. `tests/conftest.py` 的 client/session fixture 具体名称 —— Task 10 测试按现有路由测试同款 fixture 命名，执行时对齐。
2. `render_template("index.html")` 是否需要额外上下文变量 —— 照 `app/routes/dashboard.py::page()` 对齐。
3. partial 用到的 CSS class（`.kpi-card/.action-list/.briefing-*` 等）若 tokens.css/base.css 无对应，复用现有总览页（dashboard）同款 class 或补最小样式，**不**扩范围重设计。
