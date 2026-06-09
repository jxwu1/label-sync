# 缺货修正信号（第一期）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把每个 SKU 近 8 周的零销周拆成「缺货零销 / 有货零销」，置信度降级只看有货零销，补货页给「疑因缺货」SKU 加标记。

**Architecture:** 方案 1 —— 新增缺货判定纯函数 `stockout_weeks`（只看周一快照，`qty_total<=0` 判缺货）；`refresh_forecast_output`（cron）刷新时算 `stockout_zero_weeks_last8` 存入 `forecast_output` 新列；置信度 dashboard 与补货页各自只读这一列。一处算、多处读，与现有 `nonzero_weeks/zero_weeks_last8` 完全同构。

**Tech Stack:** Python 3.12 + SQLAlchemy 2.x + Alembic + pytest（离线 SQLite）+ Alpine.js/Vanilla JS 前端。

**Spec:** `docs/superpowers/specs/2026-06-09-stockout-correction-signal-design.md`（已审批）

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `app/services/stockout.py` | 缺货周判定纯函数 | 新建 |
| `tests/test_stockout.py` | stockout_weeks + 拆分函数测试 | 新建 |
| `app/services/forecast_eval.py` | 加拆分纯函数 + confidence_tier 改降级 + dashboard 读列 | 改 |
| `tests/test_confidence_tier.py` | confidence_tier 缺货不降级用例 | 改 |
| `tests/test_forecast_eval_dashboard.py` | dashboard 读新列回归 | 改 |
| `app/models.py` | ForecastOutput 加列 + 注释更新 | 改 |
| `alembic/versions/<rev>_*.py` | forecast_output 加 stockout 列 | 新建 |
| `app/services/forecast.py` | refresh 重建 series_dict + 算/写新列 | 改 |
| `app/services/analytics/summary.py` | forecast_by_bc 带出新列 | 改 |
| `app/services/analytics/restock_calc.py` | 解包新列 + 返回 item 字段 | 改 |
| `templates/partials/_page_restock.html` + `static/js/restock.js` | badge | 改 |

**约定**：全链字段名统一 `stockout_zero_weeks_last8`。判定阈值 `qty_total <= 0`。命名禁用"断货"，UI 用"疑因缺货"。

---

## Task 1: 缺货判定纯函数 `stockout_weeks`

**Files:**
- Create: `app/services/stockout.py`
- Test: `tests/test_stockout.py`

- [ ] **Step 1: 写失败测试**

`tests/test_stockout.py`：

```python
"""stockout_weeks: 周一唯一口径 + qty_total<=0 缺货判定 (spec §6 ①-⑧)。"""

from datetime import date

import pytest

from app.models import Stockpile, StockpileInventorySnapshot
from app.services.stockout import stockout_weeks


def _seed_stockpile(session, barcode="BC1", model="M1"):
    session.add(Stockpile(product_barcode=barcode, product_model=model, stockpile_location="A1"))
    session.flush()


def _add_snap(session, model, snapshot_date, qty_total):
    session.add(
        StockpileInventorySnapshot(
            snapshot_date=snapshot_date, product_model=model, qty_total=qty_total
        )
    )
    session.flush()


# 三个连续周一 (ISO): 2026-05-25 / 2026-06-01 / 2026-06-08
_MON1, _MON2, _MON3 = "2026-05-25", "2026-06-01", "2026-06-08"
_END = date(2026, 6, 8)  # 含 6-08 的 ISO 周一 = 6-08


def test_monday_qty_zero_is_stockout(db_session):
    _seed_stockpile(db_session)
    _add_snap(db_session, "M1", _MON3, 0)
    out = stockout_weeks("BC1", _END, weeks=3, session=db_session)
    assert date(2026, 6, 8) in out


def test_monday_qty_positive_not_stockout(db_session):
    _seed_stockpile(db_session)
    _add_snap(db_session, "M1", _MON3, 5)
    out = stockout_weeks("BC1", _END, weeks=3, session=db_session)
    assert date(2026, 6, 8) not in out


def test_negative_qty_is_stockout(db_session):
    # 超卖待到货 qty_total<0 → 物理无货 → 缺货 (<=0 口径)
    _seed_stockpile(db_session)
    _add_snap(db_session, "M1", _MON3, -3)
    out = stockout_weeks("BC1", _END, weeks=3, session=db_session)
    assert date(2026, 6, 8) in out


def test_week_without_monday_snapshot_is_unknown(db_session):
    # 只有更早一周的快照, 末周无周一快照 → 末周不判缺货
    _seed_stockpile(db_session)
    _add_snap(db_session, "M1", _MON1, 0)
    out = stockout_weeks("BC1", _END, weeks=3, session=db_session)
    assert date(2026, 6, 8) not in out
    assert date(2026, 5, 25) in out


def test_same_week_monday_zero_wednesday_five_is_stockout(db_session):
    # 周一 0 周三 5: 只看周一 → 缺货 (周三那条 snapshot_date 不是周一, 被忽略)
    _seed_stockpile(db_session)
    _add_snap(db_session, "M1", _MON3, 0)
    _add_snap(db_session, "M1", "2026-06-10", 5)  # 周三
    out = stockout_weeks("BC1", _END, weeks=3, session=db_session)
    assert date(2026, 6, 8) in out


def test_same_week_monday_five_wednesday_zero_not_stockout(db_session):
    # 周一 5 周三 0: 只看周一 → 不缺货
    _seed_stockpile(db_session)
    _add_snap(db_session, "M1", _MON3, 5)
    _add_snap(db_session, "M1", "2026-06-10", 0)  # 周三售空, 忽略
    out = stockout_weeks("BC1", _END, weeks=3, session=db_session)
    assert date(2026, 6, 8) not in out


def test_multi_barcode_same_model_share_qty(db_session):
    # 两个 barcode 同 model, 快照 model 级 → 都按同一 qty_total 判
    _seed_stockpile(db_session, barcode="BC1", model="M9")
    _seed_stockpile(db_session, barcode="BC2", model="M9")
    _add_snap(db_session, "M9", _MON3, 0)
    out1 = stockout_weeks("BC1", _END, weeks=3, session=db_session)
    out2 = stockout_weeks("BC2", _END, weeks=3, session=db_session)
    assert date(2026, 6, 8) in out1
    assert date(2026, 6, 8) in out2


def test_barcode_without_model_returns_empty(db_session):
    out = stockout_weeks("NO_SUCH_BC", _END, weeks=3, session=db_session)
    assert out == set()
```

> **依赖确认**：`tests/conftest.py` 须提供 `db_session` fixture（建表 + 隔离 session）。运行前用 `grep -n "def db_session" tests/conftest.py` 确认；若 fixture 名不同（如 `session`），全文替换 fixture 名。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_stockout.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.stockout'`

- [ ] **Step 3: 写实现**

`app/services/stockout.py`：

```python
"""缺货周判定 (spec 2026-06-09 §5.1)。

第一期地基: 用周一库存快照判定某周是否缺货, 供置信度分层"有货零销 vs 缺货
零销"拆分, 以及第二期需求清洗复用。

判定口径 (经 review 收紧):
- 周键 = 各 ISO 周的周一 date。
- 周一唯一: 只看 snapshot_date == 该周周一 的快照, 不取周中/最接近的快照。
- 该周一快照 qty_total <= 0 → 缺货 (负库存=ERP 超卖待到货=物理无货, 同
  restock_calc.py:197 "<0 视为 0 库存" 口径)。
- 无周一快照 → unknown, 不判缺货 (保守)。
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Stockpile, StockpileInventorySnapshot
from app.repositories import stockpile_db
from app.utils.forecast_data import _monday


def stockout_weeks(
    barcode: str,
    end_date: date,
    weeks: int,
    session: Session | None = None,
) -> set[date]:
    """返回窗口内判定为缺货的周 (周一 date 集合)。

    窗口与 weekly_demand_series 对齐: 末周 = 含 end_date 的 ISO 周, 向前 weeks 周。
    """
    if weeks < 1:
        raise ValueError("weeks must be >= 1")
    end_monday = _monday(end_date)
    week_mondays = [end_monday - timedelta(days=7 * (weeks - 1 - i)) for i in range(weeks)]
    monday_strs = [w.isoformat() for w in week_mondays]

    def _q(s: Session) -> set[date]:
        model = s.execute(
            select(Stockpile.product_model).where(Stockpile.product_barcode == barcode)
        ).scalar_one_or_none()
        if model is None:
            return set()
        rows = s.execute(
            select(
                StockpileInventorySnapshot.snapshot_date,
                StockpileInventorySnapshot.qty_total,
            ).where(
                StockpileInventorySnapshot.product_model == model,
                StockpileInventorySnapshot.snapshot_date.in_(monday_strs),
            )
        ).all()
        return {date.fromisoformat(d) for d, qty in rows if qty <= 0}

    if session is None:
        with stockpile_db._session() as s:
            return _q(s)
    return _q(session)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_stockout.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add app/services/stockout.py tests/test_stockout.py
git commit -m "feat(stockout): 缺货周判定纯函数 stockout_weeks (周一唯一口径 qty_total<=0)"
```

---

## Task 2: 零销周拆分纯函数 `stockout_zero_weeks_last8`

**Files:**
- Modify: `app/services/forecast_eval.py`（在 `demand_history_stats` 之后新增）
- Test: `tests/test_stockout.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_stockout.py` 末尾追加：

```python
from app.services.forecast_eval import stockout_zero_weeks_last8


def _series(*pairs):
    return {date.fromisoformat(d): q for d, q in pairs}


def test_szw8_counts_only_stockout_zero_weeks():
    # 近 8 周内: 三周零销, 其中两周缺货 → 缺货零销=2
    series = _series(
        ("2026-04-20", 3), ("2026-04-27", 0), ("2026-05-04", 2),
        ("2026-05-11", 1), ("2026-05-18", 4), ("2026-05-25", 0),
        ("2026-06-01", 5), ("2026-06-08", 0),
    )
    stockout = {date(2026, 5, 25), date(2026, 6, 8)}  # 两个缺货周
    # 零销周 = 04-27 / 05-25 / 06-08; ∩ stockout = 05-25 / 06-08 → 2
    assert stockout_zero_weeks_last8(series, stockout) == 2


def test_szw8_zero_week_not_in_stockout_excluded():
    series = _series(("2026-06-01", 0), ("2026-06-08", 0))
    stockout = {date(2026, 6, 8)}  # 只有 06-08 缺货; 06-01 零销但有货
    assert stockout_zero_weeks_last8(series, stockout) == 1


def test_szw8_empty_stockout_is_zero():
    series = _series(("2026-06-01", 0), ("2026-06-08", 0))
    assert stockout_zero_weeks_last8(series, set()) == 0


def test_szw8_window_is_last_8_weeks():
    # 9 周, 最早一周缺货零销但在窗口外 → 不计
    series = _series(
        ("2026-04-13", 0), ("2026-04-20", 1), ("2026-04-27", 1),
        ("2026-05-04", 1), ("2026-05-11", 1), ("2026-05-18", 1),
        ("2026-05-25", 1), ("2026-06-01", 1), ("2026-06-08", 1),
    )
    stockout = {date(2026, 4, 13)}  # 第 9 早, 在 last8 之外
    assert stockout_zero_weeks_last8(series, stockout) == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_stockout.py -k szw8 -v`
Expected: FAIL — `ImportError: cannot import name 'stockout_zero_weeks_last8'`

- [ ] **Step 3: 写实现**

在 `app/services/forecast_eval.py` 的 `demand_history_stats` 函数（54 行 `return` 之后）下方新增：

```python
def stockout_zero_weeks_last8(series: dict, stockout: set) -> int:
    """近 8 周里「需求 <= 0 且 该周在缺货集合」的周数 = 缺货零销周数 (spec §5.2)。

    series: dict[周一 date, qty]; stockout: stockout_weeks() 返回的缺货周集合。
    """
    last8 = sorted(series)[-8:]
    return sum(1 for w in last8 if series[w] <= 0 and w in stockout)
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_stockout.py -k szw8 -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add app/services/forecast_eval.py tests/test_stockout.py
git commit -m "feat(stockout): 零销周拆分 stockout_zero_weeks_last8 (近8周 缺货∩零销)"
```

---

## Task 3: `confidence_tier` 降级改用有货零销

**Files:**
- Modify: `app/services/forecast_eval.py`（`confidence_tier` 62-109 + 顶部 docstring 7-9 行）
- Test: `tests/test_confidence_tier.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_confidence_tier.py` 末尾追加（先确认文件顶部已 `from app.services.forecast_eval import confidence_tier`；若无则在新增块内 import）：

```python
from app.services.forecast_eval import confidence_tier as _ct


def test_six_zero_all_stockout_no_downgrade():
    # 近8周6周零销但全是缺货零销 → 有货零销=0 < 6 → 不降级
    res = _ct(
        history_weeks=60, nonzero_weeks=20, mase=0.8, coverage_p98=0.97,
        zero_weeks_last8=6, stockout_zero_weeks_last8=6,
    )
    assert res.tier == "high"
    assert "downgrade:recent_zero_demand" not in res.reasons


def test_six_zero_all_in_stock_downgrades():
    # 6周零销且全有货 → 有货零销=6 >= 6 → 降级 (回归现有行为)
    res = _ct(
        history_weeks=60, nonzero_weeks=20, mase=0.8, coverage_p98=0.97,
        zero_weeks_last8=6, stockout_zero_weeks_last8=0,
    )
    assert res.tier == "medium"
    assert "downgrade:recent_zero_demand" in res.reasons


def test_mixed_in_stock_below_threshold_no_downgrade():
    # 4 有货零销 + 3 缺货零销 (共7零销): 有货零销=4 < 6 → 不降级
    res = _ct(
        history_weeks=60, nonzero_weeks=20, mase=0.8, coverage_p98=0.97,
        zero_weeks_last8=7, stockout_zero_weeks_last8=3,
    )
    assert res.tier == "high"


def test_default_stockout_param_matches_legacy():
    # 不传 stockout_zero_weeks_last8 (默认0) → 行为同现状
    res = _ct(
        history_weeks=60, nonzero_weeks=20, mase=0.8, coverage_p98=0.97,
        zero_weeks_last8=6,
    )
    assert res.tier == "medium"
    assert "downgrade:recent_zero_demand" in res.reasons
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_confidence_tier.py -k "stockout or in_stock or legacy" -v`
Expected: FAIL — `TypeError: confidence_tier() got an unexpected keyword argument 'stockout_zero_weeks_last8'`

- [ ] **Step 3: 改实现**

3a. `app/services/forecast_eval.py` 顶部 docstring（7-9 行）替换为：

```python
命名约定: 近期零需求信号叫 `recent_zero_demand`。第1期接入库存快照后(spec
2026-06-09), 降级只看"有货零销"(in_stock_zero = zero_weeks_last8 -
stockout_zero_weeks_last8); 缺货导致的零销周不降级, reason 附 stockout_suppressed。
```

3b. `confidence_tier` 签名（62-69 行）增参数：

```python
def confidence_tier(
    *,
    history_weeks: int,
    nonzero_weeks: int,
    mase: float | None,
    coverage_p98: float | None,
    zero_weeks_last8: int,
    stockout_zero_weeks_last8: int = 0,
) -> ConfidenceResult:
```

3c. 降级块（100-107 行）替换为：

```python
    # 降级: 只看"有货零销"(缺货零销不算需求不足)。有货零销偏多 → 信号不可靠, 降一级。
    in_stock_zero = zero_weeks_last8 - stockout_zero_weeks_last8
    if in_stock_zero >= _RECENT_ZERO_DOWNGRADE:
        idx = _TIERS.index(tier)
        if idx > 0:
            tier = _TIERS[idx - 1]
            reasons.append("downgrade:recent_zero_demand")
        else:
            reasons.append("recent_zero_demand")
    if stockout_zero_weeks_last8 > 0:
        reasons.append("stockout_suppressed")
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_confidence_tier.py -v`
Expected: PASS（含新 4 例 + 原有例全过）

- [ ] **Step 5: 提交**

```bash
git add app/services/forecast_eval.py tests/test_confidence_tier.py
git commit -m "feat(stockout): confidence_tier 降级改用有货零销 (缺货零周不降级)"
```

---

## Task 4: alembic 迁移 + ForecastOutput 加列

**Files:**
- Create: `alembic/versions/<rev>_forecast_output_stockout_zero.py`
- Modify: `app/models.py`（ForecastOutput 442 行后 + 439-440 注释）

- [ ] **Step 1: 改 model**

`app/models.py`：442 行 `zero_weeks_last8` 之后插入：

```python
    # stockout_zero_weeks_last8 (spec 2026-06-09): 近 8 周里"缺货(周一 qty<=0)且零销"
    # 的周数; 置信度降级减掉它(只看有货零销), 补货页据此标记"疑因缺货"。
    stockout_zero_weeks_last8: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
```

并把 439-440 行原注释（"命名刻意不叫断货——无库存快照证明不了 stockout"）更新为：

```python
    # 置信度分层输入: nonzero_weeks=>0 的周数; zero_weeks_last8=最近 8 周 <=0 的周数;
    # stockout_zero_weeks_last8=其中因缺货(周一快照 qty<=0)导致的零销周数。
```

- [ ] **Step 2: 生成迁移**

Run: `python -m alembic revision -m "forecast_output 加 stockout_zero_weeks_last8 列"`
然后编辑生成的文件，确认 `down_revision = "b2c4e6f8a1d3"`，upgrade/downgrade 写为：

```python
def upgrade() -> None:
    op.add_column(
        "forecast_output",
        sa.Column("stockout_zero_weeks_last8", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("forecast_output", "stockout_zero_weeks_last8")
```

> 不要用 `--autogenerate`（本仓多模型，避免误抓其它漂移）。手写上面两个函数。

- [ ] **Step 3: 应用迁移 + 验证**

Run: `python -m alembic upgrade head`
Expected: 无报错；`python -m alembic current` 显示新 rev。

- [ ] **Step 4: 提交**

```bash
git add app/models.py alembic/versions/
git commit -m "feat(stockout): forecast_output 加 stockout_zero_weeks_last8 列 + 迁移"
```

---

## Task 5: `refresh_forecast_output` 接线写新列

**Files:**
- Modify: `app/services/forecast.py`（15-21 import + 116-148 refresh 循环）
- Test: `tests/test_stockout.py`（追加 refresh 集成回归）

- [ ] **Step 1: 写失败测试**

在 `tests/test_stockout.py` 末尾追加：

```python
def test_refresh_writes_stockout_column(db_session, monkeypatch):
    """refresh_forecast_output 把 stockout_zero_weeks_last8 写进 forecast_output。"""
    from sqlalchemy import select

    from app.models import ForecastOutput
    from app.services import forecast as fc

    bc = "BCX"
    db_session.add(Stockpile(product_barcode=bc, product_model="MX", stockpile_location="A1"))
    db_session.flush()

    end = date(2026, 6, 8)
    # _build_series 返回 (list[float], sku_type); 末周(6-08)零销 + 该周缺货
    monkeypatch.setattr(
        fc, "_build_series",
        lambda barcode, end_date, weeks, view, session=None: ([1.0] * 12 + [0.0], "retail_dominant"),
    )
    _add_snap(db_session, "MX", "2026-06-08", 0)  # 末周周一缺货

    fc.refresh_forecast_output(end_date=end, weeks=13, barcodes=[bc], session=db_session)

    row = db_session.execute(
        select(ForecastOutput).where(ForecastOutput.product_barcode == bc)
    ).scalar_one()
    assert row.stockout_zero_weeks_last8 == 1
```

> **签名核对**：打开 `app/services/forecast.py` 确认 `refresh_forecast_output` 是否接受 `session=` 参数（当前实现用内部 `with stockpile_db._session() as s`）。若现签名不含 `session`，在本 task Step 3 顺带加 `session: Session | None = None` 形参，并让函数体优先用传入 session（与 `weekly_demand_series` 同模式），再据此跑测试。二选一对齐，勿测试/实现两套口径。

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_stockout.py -k refresh -v`
Expected: FAIL — `AssertionError`（新列未写，默认 0 ≠ 1）或签名不符的 `TypeError`

- [ ] **Step 3: 改实现**

3a. `app/services/forecast.py` 顶部 import（15-21 行区）补充：

```python
from datetime import timedelta

from app.services.backtest import ForecastDist, _build_series
from app.services.forecast_eval import demand_history_stats, stockout_zero_weeks_last8
from app.services.stockout import stockout_weeks
from app.utils.forecast_data import _monday
```

> `import datetime as dt` 已存在；额外补 `from datetime import timedelta`（或用 `dt.timedelta`，与文件现有风格一致即可）。

3b. refresh 循环（128-147 行）：在 `nonzero_weeks, zero_weeks_last8 = demand_history_stats(series)` 之后、`s.execute(delete(...))` 之前插入：

```python
            # 缺货零销周数 (spec 2026-06-09): 重建与 _build_series sorted keys 同口径
            # 的周一列表 (不改 _build_series 返回契约), zip 成 dict 判周。
            end_monday = _monday(end_date)
            n = len(series)
            week_keys = [end_monday - timedelta(days=7 * (n - 1 - i)) for i in range(n)]
            series_dict = dict(zip(week_keys, series))
            sw = stockout_weeks(bc, end_date, weeks, session=s)
            szw8 = stockout_zero_weeks_last8(series_dict, sw)
```

并在 `insert(ForecastOutput).values(...)` 里加一行（紧跟 `zero_weeks_last8=zero_weeks_last8,`）：

```python
                    stockout_zero_weeks_last8=szw8,
```

> 循环变量是 `bc`（116 行 `for bc in barcodes`）与 session `s`（107 行）。`stockout_weeks(bc, end_date, weeks, session=s)` 复用同 session。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_stockout.py -k refresh -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/forecast.py tests/test_stockout.py
git commit -m "feat(stockout): refresh_forecast_output 算并写 stockout_zero_weeks_last8"
```

---

## Task 6: dashboard 聚合读新列并传入 confidence_tier

**Files:**
- Modify: `app/services/forecast_eval.py`（209-234 dashboard 聚合）
- Test: `tests/test_forecast_eval_dashboard.py`

- [ ] **Step 1: 写失败测试**

先 `grep -n "def \|ForecastOutput(\|BacktestRun(\|BacktestResult(" tests/test_forecast_eval_dashboard.py` 找现有构造 helper + dashboard 函数真名，仿照加一例：一行 `zero_weeks_last8=6, stockout_zero_weeks_last8=6` + 对应高分 backtest，断言该 SKU 落 `high`（未降级）。若无现成 helper，新增（函数名/必填字段以 `forecast_eval.py:115-260` 与 `app/models.py` BacktestRun/BacktestResult 实际定义为准）：

```python
def test_dashboard_stockout_zero_not_downgraded(db_session):
    from app.models import BacktestResult, BacktestRun, ForecastOutput
    from app.services.forecast_eval import backtest_dashboard  # 以实际函数名为准

    db_session.add(ForecastOutput(
        product_barcode="BCD", model_used="EmpiricalQuantile", sku_type="retail_dominant",
        n_weeks_history=60, nonzero_weeks=20, zero_weeks_last8=6,
        stockout_zero_weeks_last8=6, mu=1.0, sigma=1.0, p50=1.0, p98=2.0,
    ))
    run = BacktestRun(model_name="EmpiricalQuantile", view="base_demand", end_date="2026-06-08")
    db_session.add(run); db_session.flush()
    db_session.add(BacktestResult(
        run_id=run.id, product_barcode="BCD", mase=0.8, coverage_p98=0.97,
    ))
    db_session.flush()

    out = backtest_dashboard(db_session)  # 以实际签名为准
    assert out["tiers"]["high"] >= 1
```

> **以实际为准**：dashboard 聚合函数真名/签名、`BacktestRun`/`BacktestResult` 必填字段，打开 `forecast_eval.py:115-260` 与 `app/models.py:351-386` 核对后填。本步只为锁定"读新列 → 高分缺货零销不降级"这条断言。

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_forecast_eval_dashboard.py -k stockout -v`
Expected: FAIL（当前 select 未读新列，confidence_tier 未拿到 stockout → 被降级到 medium，high 计数不增）

- [ ] **Step 3: 改实现**

`app/services/forecast_eval.py` 209-217 行 select 增列：

```python
    rows = session.execute(
        select(
            ForecastOutput.product_barcode,
            ForecastOutput.sku_type,
            ForecastOutput.n_weeks_history,
            ForecastOutput.nonzero_weeks,
            ForecastOutput.zero_weeks_last8,
            ForecastOutput.stockout_zero_weeks_last8,
        )
    ).all()
```

226-234 行循环解包 + 调用：

```python
    for bc, sku_type, hist, nz, z8, szw8 in rows:
        mase, cov = metrics.get(bc, (None, None))
        res = confidence_tier(
            history_weeks=hist,
            nonzero_weeks=nz,
            mase=mase,
            coverage_p98=cov,
            zero_weeks_last8=z8,
            stockout_zero_weeks_last8=szw8,
        )
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_forecast_eval_dashboard.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/forecast_eval.py tests/test_forecast_eval_dashboard.py
git commit -m "feat(stockout): dashboard 读 stockout 列传入 confidence_tier"
```

---

## Task 7: 补货页后端接线（summary + restock_calc）

**Files:**
- Modify: `app/services/analytics/summary.py`（220-236）
- Modify: `app/services/analytics/restock_calc.py`（259-300）

- [ ] **Step 1: 改 summary.py**

220-227 行 select 增列：

```python
        forecast_rows = session.execute(
            select(
                ForecastOutput.product_barcode,
                ForecastOutput.p50,
                ForecastOutput.p98,
                ForecastOutput.model_used,
                ForecastOutput.stockout_zero_weeks_last8,
            )
        ).all()
```

234-236 行 tuple 改 4 元：

```python
    forecast_by_bc: dict[str, tuple[float, float, str, int]] = {}
    for r in forecast_rows:
        forecast_by_bc[r.product_barcode] = (
            r.p50, r.p98, r.model_used, r.stockout_zero_weeks_last8,
        )
```

- [ ] **Step 2: 改 restock_calc.py**

272-276 行解包改 4 元：

```python
    if fc:
        p50, p98, model, _stockout_zw8 = fc
        qty_p50 = max(0, math.ceil(p50 * target) - stock)
        qty_p98 = max(0, math.ceil(p98 * target) - stock)
        source = f"forecast:{model}"
```

293-300 行返回 dict 增字段（`forecast_p98` 后）：

```python
    return {
        "restock_qty_p50": qty_p50,
        "restock_qty_p98": qty_p98,
        "restock_source": source,
        "last_purchase_qty": last_pq,
        "forecast_p50": round(fc[0], 2) if fc else None,
        "forecast_p98": round(fc[1], 2) if fc else None,
        "stockout_zero_weeks_last8": fc[3] if fc else 0,
    }
```

- [ ] **Step 3: 运行回归**

Run: `pytest tests/ -k "restock or summary" -v`
Expected: PASS（tuple 解包改动无回归）

- [ ] **Step 4: 提交**

```bash
git add app/services/analytics/summary.py app/services/analytics/restock_calc.py
git commit -m "feat(stockout): 补货行带出 stockout_zero_weeks_last8 字段"
```

---

## Task 8: 补货页前端 badge

**Files:**
- Modify: `templates/partials/_page_restock.html`
- Modify: `static/js/restock.js`
- Modify: `static/css/components.css`（badge 样式，路径以实际为准）

- [ ] **Step 1: 定位渲染点**

Run: `grep -n "restock_source\|forecast_p98\|疑因\|badge\|rs-flag\|it\." static/js/restock.js templates/partials/_page_restock.html`
找到补货行/抽屉里渲染 `restock_source` 或 p98 的位置（item 字段已含 `stockout_zero_weeks_last8`）。判定该行由 Alpine 模板（`x-text`/`x-for`）还是 JS 字符串拼接生成。

- [ ] **Step 2: 加 badge**

若补货行是 Alpine 模板（`<template x-for>` 里 `it`），在型号/来源标签附近插入：

```html
<span x-show="it.stockout_zero_weeks_last8 > 0"
      class="rs-badge-stockout"
      x-text="'⚠ 近 ' + it.stockout_zero_weeks_last8 + ' 周零销疑因缺货'"></span>
```

若补货行由 `restock.js` 字符串拼接生成，则在对应行模板插入等价片段：

```js
const stockoutBadge = it.stockout_zero_weeks_last8 > 0
  ? `<span class="rs-badge-stockout">⚠ 近 ${it.stockout_zero_weeks_last8} 周零销疑因缺货</span>`
  : "";
```
并把 `stockoutBadge` 拼进该行 HTML。

> 二选一，与该文件现有补货行其它标签的写法保持一致。

- [ ] **Step 3: 加最小样式**

`static/css/components.css`（或 grep 出的补货页样式表）加：

```css
.rs-badge-stockout {
  color: var(--warn, #b45309);
  font-size: 12px;
  white-space: nowrap;
}
```

- [ ] **Step 4: 本地验证**

Run: `LABEL_SYNC_DEBUG=1 python server.py`（或 `./dev.ps1`），浏览器开补货页确认：有 `stockout_zero_weeks_last8>0` 的行显示 badge、为 0 的行不显示、文案无"断货"。
（本地 PG 需灌一条合成 forecast_output(`stockout_zero_weeks_last8>0`) + 对应 sku_summary 行；参照 spec §6 验收与上次 boson 走查的合成数据流程。验证后清理合成行。）

- [ ] **Step 5: 提交**

```bash
git add templates/partials/_page_restock.html static/js/restock.js static/css/components.css
git commit -m "feat(stockout): 补货页 疑因缺货 badge"
```

---

## Task 9: 全量回归 + 收尾

- [ ] **Step 1: 全量测试**

Run: `pytest tests/ -q`
Expected: 全过（基线 1117 + 本次新增用例）

- [ ] **Step 2: 自检命名纪律**

Run: `grep -rn "断货" app/ templates/ static/js/`
Expected: 无新增"断货"（历史无关命中可忽略）

- [ ] **Step 3: 分支收尾**

按 `superpowers:finishing-a-development-branch`：squash merge 回 main（push main 走护栏 `block-push-main.js`，用户自己 `!git push`）。线上部署后需 `alembic upgrade head` 应用新列（参照 `project_local_alembic_2385c_missing_columns` 模式，线上迁移正常）。

---

## Self-Review（plan vs spec）

- **§5.1 stockout_weeks** → Task 1（8 用例全覆盖周一口径/<=0/负库存/多barcode/无model）✓
- **§5.2 拆分函数** → Task 2 ✓
- **§5.3 存储 + series 契约** → Task 4（列）+ Task 5（refresh 重建 series_dict，明确不改 _build_series）✓
- **§5.4 置信度降级** → Task 3（in_stock_zero + stockout_suppressed）✓
- **§5.5 补货页标记** → Task 7（后端字段）+ Task 8（badge）✓
- **§6 测试边界**（同周多快照/负库存/默认参数兼容/dashboard 回归）→ Task 1/3/6 ✓
- **§7 命名纪律** → Task 9 Step 2 grep 守卫 ✓
- 字段名全链 `stockout_zero_weeks_last8` 一致：model/migration/refresh/dashboard/summary/restock_calc/JS ✓
- 阈值 `<= 0` 一致：stockout_weeks 实现 + Task 1 负库存用例 ✓
