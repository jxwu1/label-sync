# 补货正确性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 ADR-0001 的三个正确性修复（跨期聚合 RL-1、在途扣减 RL-2、删失剔除 RL-3）及配套红线（RL-4/6/8/9/10），解除 `tests/test_replenishment_redlines.py` 全部 skip。

**Architecture:** 纯函数先行（horizon_quantile / on_order / exclude），再 schema 加列，再 refresh 写入，最后 restock 消费端重写。每个 Task 以解除对应 skip 测试为验收。

**Tech Stack:** numpy bootstrap、SQLAlchemy 2.x、Alembic autogenerate、pytest（先 sqlite 快循环，合并前 `./test.ps1` 过 PG 腿）。

**前置阅读:** `docs/adr/0001-replenishment-policy.md`（决策依据，本 plan 不重复论证）、`docs/adr/replenishment-redlines.md`（RL 编号定义）。

**测试骨架已存在:** `tests/test_replenishment_redlines.py` 已写好全部预期值并标 skip。每个 Task 的"写测试"步骤 = 删除对应 class 的 `@pytest.mark.skip` 行。

---

### Task 1: horizon_quantile — bootstrap 跨期分位数（RL-1）

**Files:**
- Modify: `app/services/forecast.py`（`_Z98` 常量之后、`_zero_dist` 之前加函数）
- Test: `tests/test_replenishment_redlines.py::TestRL1HorizonQuantile`（解除 skip）

- [ ] **Step 1: 解除 skip**

删除 `TestRL1HorizonQuantile` 上方的 `@pytest.mark.skip(...)` 行。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_replenishment_redlines.py::TestRL1HorizonQuantile -v`
Expected: 5 个 FAIL，`ImportError: cannot import name 'horizon_quantile'`

- [ ] **Step 3: 实现**

在 `app/services/forecast.py` 的 `_Z98 = 2.054` 行之后加：

```python
def horizon_quantile(
    history: list[float],
    horizon_weeks: int,
    q: float,
    n_boot: int = 2000,
    seed: int = 42,
) -> float:
    """H 周需求总和的经验分位数（bootstrap，ADR-0001 D5 / RL-1）.

    周分位数不可线性放大到多周（Q_α(ΣD) ≪ N·Q_α(D)，√N 律），
    这里有放回抽 horizon_weeks 个周值求和 × n_boot 次，取和的分位数。
    i.i.d. 假设与 EmpiricalQuantile 模型一致。固定 seed 保证可复现。
    """
    if not history or horizon_weeks < 1:
        return 0.0
    arr = np.asarray(history, dtype=float)
    rng = np.random.default_rng(seed)
    sums = rng.choice(arr, size=(n_boot, horizon_weeks), replace=True).sum(axis=1)
    return float(max(0.0, np.quantile(sums, q)))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_replenishment_redlines.py::TestRL1HorizonQuantile -v`
Expected: 5 PASS（含恒定序列精确等于 40.0、固定 seed 可复现）

- [ ] **Step 5: Commit**

```bash
git add app/services/forecast.py tests/test_replenishment_redlines.py
git commit -m "feat(forecast): horizon_quantile bootstrap 跨期分位数 (RL-1)"
```

---

### Task 2: 短序列尾部收缩（RL-4）

**Files:**
- Modify: `app/services/forecast.py:68-79`（`EmpiricalQuantileModel.fit`）
- Test: `tests/test_replenishment_redlines.py::TestRL4ShortSeriesTail`（解除 skip）

- [ ] **Step 1: 解除 skip，跑测试确认失败**

Run: `pytest tests/test_replenishment_redlines.py::TestRL4ShortSeriesTail -v`
Expected: `test_rl4_short_series_tail_shrinkage` FAIL（当前 p98 ≈ 76.2 > 1.5）

- [ ] **Step 2: 实现**

`EmpiricalQuantileModel` 类定义前加常量：

```python
_SHRINK_BELOW_WEEKS = 30  # 序列短于此用收缩尾部 (RL-4)
_SHRINK_P90_FACTOR = 1.5
```

`fit` 中替换 `p98 = float(np.quantile(arr, 0.98))` 与 `p98 = max(p98, 0.0)` 两行为：

```python
        p98 = float(np.quantile(arr, 0.98))
        if len(arr) < _SHRINK_BELOW_WEEKS:
            # RL-4: 小样本经验 p98 ≈ max(单笔大单)，用 p90×1.5 收缩
            p90 = float(np.quantile(arr, 0.90))
            p98 = min(p98, p90 * _SHRINK_P90_FACTOR)
        p98 = max(p98, p50, 0.0)  # 收缩不破坏 p50 ≤ p98 单调
```

- [ ] **Step 3: 跑测试确认通过 + 全文件回归**

Run: `pytest tests/test_replenishment_redlines.py tests/ -q -k "forecast"`
Expected: TestRL4 3 PASS；既有 forecast 测试如有断言短序列 p98 精确值的需同步更新（预期值变小是本修复的目的，不是回归）

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(forecast): 短序列 p98 收缩估计 (RL-4)"
```

---

### Task 3: on_order_by_barcode — 在途量查询（RL-2 前半）

**Files:**
- Modify: `app/services/purchase.py`（文件末尾加函数）
- Test: `tests/test_replenishment_redlines.py::TestRL2OnOrderNetting`（解除 skip；其中 `test_rl2_on_order_netting` 依赖 Task 7 的新签名，本 Task 给它单独临时加 `@pytest.mark.skip(reason="待 Task 7")`，Task 7 解除）

- [ ] **Step 1: 解除 class skip + 给 netting 测试加临时 skip，跑测试确认失败**

Run: `pytest tests/test_replenishment_redlines.py::TestRL2OnOrderNetting -v`
Expected: partial/void/over_receipt 3 FAIL（`ImportError: cannot import name 'on_order_by_barcode'`），netting 1 SKIP

- [ ] **Step 2: 实现**

`app/services/purchase.py` 末尾加：

```python
def on_order_by_barcode(session) -> dict[str, int]:
    """各 SKU 在途量 = Σ max(0, qty_ordered − qty_arrived)，非作废单（RL-2）.

    只返回在途 > 0 的条目。超收（arrived > ordered）按 0 计不为负。
    """
    from sqlalchemy import select

    from app.models import PurchaseOrder, PurchaseOrderLine

    rows = session.execute(
        select(
            PurchaseOrderLine.product_barcode,
            PurchaseOrderLine.qty_ordered,
            PurchaseOrderLine.qty_arrived,
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.order_id)
        .where(PurchaseOrder.status.not_in(("cancelled", "void")))
    ).all()
    out: dict[str, int] = {}
    for bc, ordered, arrived in rows:
        pending = max(0, int(ordered or 0) - int(arrived or 0))
        if pending > 0:
            out[bc] = out.get(bc, 0) + pending
    return out
```

- [ ] **Step 3: 跑测试确认通过**

Run: `pytest tests/test_replenishment_redlines.py -v -k "rl2"`
Expected: partial/void/over_receipt 3 PASS，netting 1 SKIP（留给 Task 7）

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(purchase): on_order_by_barcode 在途量查询 (RL-2)"
```

---

### Task 4: exclude_stockout_weeks + _build_series 接线（RL-3）

**Files:**
- Modify: `app/services/stockout.py`（末尾加函数）
- Modify: `app/services/backtest.py:281-303`（`_build_series` 返回 3-tuple）
- Modify: `app/services/backtest.py:324-327`（`run_backtest_for_sku` 解包适配）
- Modify: `app/services/forecast.py:119-141`（`refresh_forecast_output` 解包适配 + szw8 段重写）
- Test: `tests/test_replenishment_redlines.py::TestRL3StockoutExclusion`（解除 skip）

- [ ] **Step 1: 解除 skip，跑测试确认失败**

Run: `pytest tests/test_replenishment_redlines.py::TestRL3StockoutExclusion -v`
Expected: 2 FAIL（`exclude_stockout_weeks` 不存在）

- [ ] **Step 2: 实现纯函数**

`app/services/stockout.py` 末尾加：

```python
def exclude_stockout_weeks(
    series: dict[date, float],
    stockout: set[date],
) -> dict[date, float]:
    """缺货周从训练序列剔除（当缺失，不填 0 不插值）— RL-3 / ADR-0001 D7.

    缺货周的 0 销量是删失观测不是真实需求，入训练会拉低分位数 →
    补货更少 → 更缺货（死亡螺旋）。
    """
    return {wk: qty for wk, qty in series.items() if wk not in stockout}
```

- [ ] **Step 3: _build_series 接线（返回 3-tuple）**

`app/services/backtest.py` 中 `_build_series` 整体替换为：

```python
def _build_series(
    barcode: str,
    end_date,
    weeks: int,
    view: str,
    session=None,
) -> tuple[list[float], str, int] | None:
    """从 DB 拉单 SKU 周序列 + sku_type + 剔除的缺货周数. None = 不可回测.

    base_demand 视图剔除缺货周（RL-3）；all 视图保留原始信号不剔。
    """
    from app.services.stockout import exclude_stockout_weeks, stockout_weeks
    from app.utils.categorizer import classify_sku_type
    from app.utils.forecast_data import base_demand_view, weekly_demand_series

    if view == "base_demand":
        v = base_demand_view(barcode, end_date, weeks, session=session)
        if v["series"] is None:
            return None
        so = stockout_weeks(barcode, end_date, weeks, session=session)
        kept = exclude_stockout_weeks(v["series"], so)
        n_excluded = len(v["series"]) - len(kept)
        return [kept[k] for k in sorted(kept)], v["sku_type"], n_excluded
    if view == "all":
        sku_type = classify_sku_type(barcode, session=session, as_of=end_date)
        if sku_type in ("unclassified", "dying"):
            return None
        d = weekly_demand_series(barcode, end_date, weeks, session=session)
        return [d[k] for k in sorted(d)], sku_type, 0
    raise ValueError(f"unknown view: {view}")
```

`run_backtest_for_sku` 中解包行（324-327）改为：

```python
    built = _build_series(barcode, end_date, weeks, view, session)
    if built is None:
        return None
    series, sku_type, _n_excluded = built
```

- [ ] **Step 4: refresh_forecast_output 解包适配 + szw8 段重写**

`forecast.py` 的 refresh 循环中解包行改为：

```python
            built = _build_series(bc, end_date, weeks, "base_demand", session=s)
            if built is None:
                continue
            series, sku_type, n_excluded = built
```

szw8 计算段（`end_monday = _monday(end_date)` 起到 `szw8 = ...` 止）整体替换 ——
剔除后 `len(series)` 与连续周对齐不再成立，必须在剔除**前**的原始视图上算：

```python
            # 缺货零销周数: 在剔除前的原始视图上算（剔除后周键不连续）
            from app.utils.forecast_data import base_demand_view as _bdv

            raw = _bdv(bc, end_date, weeks, session=s)["series"] or {}
            sw = stockout_weeks(bc, end_date, max(len(raw), 1), session=s)
            szw8 = stockout_zero_weeks_last8(raw, sw)
```

（`raw` 本身就是 dict[周一 date, qty]，与 `stockout_zero_weeks_last8(series_dict, ...)`
口径一致；顶部 `from app.utils.forecast_data import _monday` 若再无人用可删。
注意这里对 `base_demand_view` 多查一次 —— 可接受：每周 cron 跑一次非热路径；
若要省，可让 `_build_series` 返回 4-tuple 带 raw dict，执行者自行权衡。）

- [ ] **Step 5: 跑测试**

Run: `pytest tests/test_replenishment_redlines.py::TestRL3StockoutExclusion tests/ -q -k "backtest or stockout or refresh"`
Expected: RL-3 2 PASS；既有测试全过（无缺货 seed 的测试 n_excluded=0 行为不变）

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(forecast): 缺货周从训练序列剔除 (RL-3)"
```

---

### Task 5: lead time 配置 + 经验切换（ADR D4）

**Files:**
- Modify: `app/config.py`（用既有 `_env_int` 惯例加配置）
- Modify: `app/services/purchase.py`（末尾加 `lead_time_weeks`）
- Test: `tests/test_replenishment_redlines.py` 新增 `TestLeadTime`（本 Task 现写）

- [ ] **Step 1: 写测试**

`tests/test_replenishment_redlines.py` 末尾加：

```python
class TestLeadTime:
    """ADR-0001 D4: lead time 先验 + 经验切换。"""

    def test_prior_when_insufficient_samples(self):
        from app.repositories import stockpile_db
        from app.services.purchase import lead_time_weeks

        with stockpile_db._session() as s:
            weeks, source, n = lead_time_weeks(s)
        assert source == "prior"
        assert weeks >= 1

    def test_empirical_p90_when_enough_samples(self):
        from app.models import PurchaseOrder
        from app.repositories import stockpile_db
        from app.services.purchase import lead_time_weeks

        with stockpile_db._session() as s:
            # 20 单：19 单 lead 21 天 + 1 单 70 天 → p90 = 21 天 → 3 周
            for _ in range(19):
                s.add(
                    PurchaseOrder(
                        order_date="2026-01-01", arrival_date="2026-01-22", status="arrived"
                    )
                )
            s.add(
                PurchaseOrder(
                    order_date="2026-01-01", arrival_date="2026-03-12", status="arrived"
                )
            )
            s.commit()
            weeks, source, n = lead_time_weeks(s)
        assert source == "empirical"
        assert n == 20
        assert weeks == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_replenishment_redlines.py::TestLeadTime -v`
Expected: 2 FAIL（`lead_time_weeks` 不存在）

- [ ] **Step 3: 实现**

`app/config.py` 中其他 `_env_int` 用法附近加：

```python
# 补货 lead time 先验（周）。ADR-0001 D4：PO 到货样本 ≥20 后自动切经验 p90。
# 默认 4 周 = 用户 2026-06-11 校准值（中国采购→希腊到货）。
REPLENISH_LEAD_TIME_WEEKS = _env_int("REPLENISH_LEAD_TIME_WEEKS", 4)
```

`app/services/purchase.py` 末尾加：

```python
_LEAD_TIME_MIN_SAMPLES = 20
_LEAD_TIME_MAX_PLAUSIBLE_DAYS = 365  # 超一年的样本视为脏数据


def lead_time_weeks(session) -> tuple[int, str, int]:
    """补货 lead time（周）— (weeks, source, n_samples)，ADR-0001 D4.

    样本 ≥ 20 单 → 经验 p90 天数向上取整为周（右偏分布取 p90 偏保守）；
    否则配置先验 REPLENISH_LEAD_TIME_WEEKS。source ∈ {'prior', 'empirical'}。
    """
    import datetime as dt
    import math

    import numpy as np
    from sqlalchemy import select

    from app import config
    from app.models import PurchaseOrder

    rows = session.execute(
        select(PurchaseOrder.order_date, PurchaseOrder.arrival_date).where(
            PurchaseOrder.arrival_date.is_not(None),
            PurchaseOrder.status.not_in(("cancelled", "void")),
        )
    ).all()
    days = []
    for od, ad in rows:
        try:
            d = (dt.date.fromisoformat(ad[:10]) - dt.date.fromisoformat(od[:10])).days
        except (ValueError, TypeError):
            continue
        if 0 <= d <= _LEAD_TIME_MAX_PLAUSIBLE_DAYS:
            days.append(d)
    if len(days) >= _LEAD_TIME_MIN_SAMPLES:
        p90 = float(np.quantile(np.asarray(days, dtype=float), 0.90))
        return max(1, math.ceil(p90 / 7)), "empirical", len(days)
    return config.REPLENISH_LEAD_TIME_WEEKS, "prior", len(days)
```

（验算：19×21 天 + 1×70 天，p90 位置 = 0.9×19 = 17.1 → 排序后 [21]×19+[70]，
索引 17.1 处仍是 21 → ceil(21/7) = 3 周 ✓）

- [ ] **Step 4: 跑测试确认通过，Commit**

Run: `pytest tests/test_replenishment_redlines.py::TestLeadTime -v`
Expected: 2 PASS

```bash
git commit -am "feat(purchase): lead time 先验配置 + 经验 p90 自动切换 (ADR D4)"
```

---

### Task 6: forecast_output 加列 + refresh 写入 horizon 分位数

**Files:**
- Modify: `app/models.py:426-475`（`ForecastOutput` 加 5 列）
- Create: `alembic/versions/<autogen>_forecast_output_horizon_cols.py`（autogenerate）
- Modify: `app/services/forecast.py`（`refresh_forecast_output` 写新列）

- [ ] **Step 1: models.py 加列**

`ForecastOutput` 类中 `p98` 字段之后加：

```python
    # ADR-0001: 保护期 H = R + L 的 horizon 分位数（bootstrap，RL-1 修复）。
    # 消费端用这两列，不得再用 周分位 × N。
    horizon_weeks: Mapped[int | None] = mapped_column(Integer)
    p50_h: Mapped[float | None] = mapped_column()
    p98_h: Mapped[float | None] = mapped_column()
    p98_13w: Mapped[float | None] = mapped_column()  # 季度展示口径
    stockout_weeks_excluded: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
```

- [ ] **Step 2: 生成迁移并升级**

```bash
python -m alembic revision --autogenerate -m "forecast_output horizon cols"
python -m alembic upgrade head
```

检查生成的迁移只含这 5 列的 add_column。
（本地 PG 若撞既有 `2385c` 撞表问题：照迁移内容手动
`ALTER TABLE forecast_output ADD COLUMN IF NOT EXISTS ...` 补齐后 `alembic stamp head`。）

- [ ] **Step 3: refresh 写入**

`refresh_forecast_output` 中，session 打开后（拉 barcodes 之前）加：

```python
        from app.services.purchase import lead_time_weeks

        lt_weeks, lt_source, _lt_n = lead_time_weeks(s)
        horizon = 1 + lt_weeks  # H = R + L, R=1 周（ADR D1/D2）
```

模型 fit 段之后、insert 之前加：

```python
            p50_h = horizon_quantile(series, horizon, 0.50)
            p98_h = horizon_quantile(series, horizon, 0.98)
            p98_13w = horizon_quantile(series, 13, 0.98)
```

`insert(ForecastOutput).values(...)` 中加对应字段：

```python
                    horizon_weeks=horizon,
                    p50_h=p50_h,
                    p98_h=p98_h,
                    p98_13w=p98_13w,
                    stockout_weeks_excluded=n_excluded,
```

返回 dict 加 `"horizon_weeks": horizon, "lead_time_source": lt_source`。

- [ ] **Step 4: 跑 refresh 相关既有测试**

Run: `pytest tests/ -q -k "refresh or forecast_output"`
Expected: 全过（新列可空，旧断言不破坏）

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(forecast): forecast_output 增加 horizon 分位数列 + refresh 写入"
```

---

### Task 7: _restock_recommendation 重写 — 消费 horizon 列 + 在途 + 反震荡 + 合理性闸（RL-2/6/8 收口）

**Files:**
- Modify: `app/services/analytics/restock_calc.py:254-300`（重写）+ `:41-73`（snapshot 季度口径）
- Modify: `app/services/analytics/summary.py:220-241`（select 新列）、`:538` 附近（传 on_order）
- Test: 解除 `test_rl2_on_order_netting` 临时 skip、`TestRL6SanityGate`、`TestRL8AntiChurn` 的 skip

- [ ] **Step 1: 解除上述三组 skip，跑测试确认失败**

Run: `pytest tests/test_replenishment_redlines.py -v -k "rl2_on_order or rl6 or rl8"`
Expected: 5 FAIL（`on_order` 参数不存在 / `sanity_flag` 键不存在 / 反震荡未实现）

- [ ] **Step 2: 重写 _restock_recommendation**

`restock_calc.py` 中 `_restock_recommendation` 整体替换（含前置常量与 `_churn_gate`）：

```python
_CHURN_MIN_FRACTION = 0.25  # 反震荡: 缺口 < 25% S 且不足一个中包 → 持有 (RL-8)
_SANITY_HISTORICAL_MULT = 3  # 合理性闸: 推荐 > 历史最大单次进货 × 3 → 标记 (RL-6)
_SANITY_PACK_MULT = 10


def _churn_gate(qty: int, s_level: int, stock: int, pack: int | None) -> int:
    """RL-8 反震荡触发阈值（ADR D6）。断货必触发；缺口不足阈值 → 持有(0)。"""
    if qty <= 0:
        return 0
    if stock <= 0 and s_level > 0:
        return qty
    threshold = max(pack or 1, _CHURN_MIN_FRACTION * s_level)
    return qty if qty >= threshold else 0


def _restock_recommendation(
    barcode: str,
    qty_total: int,
    weekly_velocity: float,
    forecast_by_bc: dict,
    last_purchase_qty_by_bc: dict,
    middle_qty: int | None = None,
    on_order: int = 0,
) -> dict:
    """推荐补货量 = max(0, S − IP)，S = horizon 分位数（ADR-0001 D2）.

    IP = 现库存(负取0) + 在途(RL-2)。fc 元组为 (p50_h, p98_h, model, szw8) ——
    forecast_output 的 horizon 列，已是 H 周总量，不得再乘周数（RL-1）。
    回退链: forecast → velocity(×8周口径) → last_purchase。
    """
    import math

    target = _RESTOCK_TARGET_WEEKS  # 仅 velocity 回退路径使用
    last_pq = last_purchase_qty_by_bc.get(barcode)
    fc = forecast_by_bc.get(barcode)
    stock = max(0, qty_total or 0)
    ip = stock + max(0, on_order)

    if fc:
        p50_h, p98_h, model, _stockout_zw8 = fc
        s50, s98 = math.ceil(p50_h), math.ceil(p98_h)
        qty_p50 = _churn_gate(max(0, s50 - ip), s50, stock, middle_qty)
        qty_p98 = _churn_gate(max(0, s98 - ip), s98, stock, middle_qty)
        source = f"forecast:{model}"
    elif weekly_velocity > 0:
        qty_p50 = max(0, math.ceil(weekly_velocity * target) - ip)
        qty_p98 = max(0, math.ceil(weekly_velocity * target * 1.5) - ip)
        source = "velocity"
    elif last_pq:
        qty_p50 = last_pq
        qty_p98 = last_pq
        source = "last_purchase"
    else:
        qty_p50 = None
        qty_p98 = None
        source = None

    qty_p50 = _round_up_to_pack(qty_p50, middle_qty)
    qty_p98 = _round_up_to_pack(qty_p98, middle_qty)

    # RL-6 合理性闸: 只标记不截断（截断会掩盖上游 bug）
    sanity_flag = None
    if qty_p98 and last_pq:
        cap = max(
            last_pq * _SANITY_HISTORICAL_MULT,
            (middle_qty or 1) * _SANITY_PACK_MULT,
        )
        if qty_p98 > cap:
            sanity_flag = "exceeds_historical_max"

    return {
        "restock_qty_p50": qty_p50,
        "restock_qty_p98": qty_p98,
        "restock_source": source,
        "last_purchase_qty": last_pq,
        "forecast_p50": round(fc[0], 2) if fc else None,
        "forecast_p98": round(fc[1], 2) if fc else None,
        "stockout_zero_weeks_last8": fc[3] if fc else 0,
        "on_order": on_order,
        "sanity_flag": sanity_flag,
    }
```

（验算红线测试：RL-2 netting fc=(40,90) stock=10 on_order=50 → IP=60：
p50 档 40−60→0 ✓；p98 档 90−60=30，churn 阈 max(1, 22.5)=22.5，30≥22.5 → 30 ✓。
RL-8 churn fc=(20,40) stock=38：p98 缺口 2 < max(12,10) → 0 ✓；
stock=0 必触发 ✓。RL-6 (600,5000) stock=0：5000→凑整 5004 > max(2400,120) → 标记 ✓；
(16,40) stock=10：p98=30 ≤ max(300,10) → None ✓。
RL-5 守护：fc=(5,20) stock=10：p50 0、p98 10<12 →0，0≤0 单调 ✓。）

- [ ] **Step 3: summary.py 接线**

select 段（220-227）改读 horizon 列：

```python
            select(
                ForecastOutput.product_barcode,
                ForecastOutput.p50_h,
                ForecastOutput.p98_h,
                ForecastOutput.model_used,
                ForecastOutput.stockout_zero_weeks_last8,
            )
```

`forecast_by_bc` 构建段（234-241）加空值守卫（部署后首次 refresh 前旧行无新列）：

```python
    forecast_by_bc: dict[str, tuple[float, float, str, int]] = {}
    for r in forecast_rows:
        if r.p50_h is None or r.p98_h is None:
            continue  # 旧行未刷 horizon 列 → 走 velocity 回退
        forecast_by_bc[r.product_barcode] = (
            r.p50_h,
            r.p98_h,
            r.model_used,
            r.stockout_zero_weeks_last8,
        )
```

同一数据收集段（`_snapshot_qty_lookup` 调用附近）加：

```python
        from app.services.purchase import on_order_by_barcode

        on_order_map = on_order_by_barcode(session)
```

`:538` 的 `_restock_recommendation(...)` 调用加实参（其余实参名照现场抄）：

```python
                    on_order=on_order_map.get(it["barcode"], 0),
```

- [ ] **Step 4: compute_forecast_snapshot 的季度口径**

`compute_forecast_snapshot` 返回 dict 改为：

```python
        return {
            "model_used": row.model_used,
            "sku_type": row.sku_type,
            "n_weeks_history": row.n_weeks_history,
            "weekly_mu": round(float(row.mu), 2),
            "weekly_p50": round(float(row.p50), 2),
            "weekly_p98": round(float(row.p98), 2),
            "quarter_mu": round(float(row.mu) * 13, 0),  # 均值可线性相加，保留
            # RL-1: 季度 p98 用 bootstrap 列；旧行未刷则回退线性值（过渡期）
            "quarter_p98": (
                round(float(row.p98_13w), 0)
                if row.p98_13w is not None
                else round(float(row.p98) * 13, 0)
            ),
            "horizon_weeks": row.horizon_weeks,
            "p50_h": round(float(row.p50_h), 2) if row.p50_h is not None else None,
            "p98_h": round(float(row.p98_h), 2) if row.p98_h is not None else None,
            "stockout_weeks_excluded": row.stockout_weeks_excluded,
            "computed_at": row.computed_at,
        }
```

- [ ] **Step 5: 跑测试**

Run: `pytest tests/test_replenishment_redlines.py tests/test_analytics_service.py tests/test_routes_analytics.py -v`
Expected: RL-2/6/8 全 PASS；RL-5 守护测试仍 PASS（不变量在新公式下成立）；
analytics 既有测试中若有断言 `×8` 具体数值的 → 按新口径更新预期值
（这是修复的目的；commit message 里点名哪些预期值因 RL-1 更新）

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(restock): horizon 分位数 + 在途扣减 + 反震荡 + 合理性闸 (RL-1/2/6/8)"
```

---

### Task 8: RL-9/RL-10 巡检接线 + staleness 纯函数

**Files:**
- Modify: `app/services/forecast_eval.py`（加 `forecast_is_stale`；注意 `alerts.py` 已有 `_forecast_days_since` 做整表新鲜度，本函数是单行粒度补充）
- Modify: `app/services/alerts.py`（`collect_alerts` 加周一快照缺失检查）
- Test: 解除 `TestRL9Staleness` skip + 新写 `TestRL10MissingSnapshot`

- [ ] **Step 1: 解除 RL-9 skip，跑确认失败，实现**

`app/services/forecast_eval.py` 中 `_is_usable_metric` 之后加：

```python
def forecast_is_stale(
    computed_at: str | None,
    today,
    max_age_days: int = 14,
) -> bool:
    """forecast_output 行是否过期（RL-9）。None/解析失败 = 过期。"""
    import datetime as dt

    if not computed_at:
        return True
    try:
        d = dt.date.fromisoformat(str(computed_at)[:10])
    except ValueError:
        return True
    return (today - d).days > max_age_days
```

Run: `pytest tests/test_replenishment_redlines.py::TestRL9Staleness -v`
Expected: PASS

- [ ] **Step 2: RL-10 巡检 — alerts.py 加检查**

`alerts.py` 中 `_backtest_days_since` 之后加（风格对齐同文件 `_*_days_since`）：

```python
def _missing_monday_snapshots(session, as_of: date, n_weeks: int = 4) -> list[str]:
    """最近 n_weeks 个已过去的周一中无库存快照的日期（RL-10）。"""
    from datetime import timedelta

    from sqlalchemy import select

    from app.models import StockpileInventorySnapshot
    from app.utils.forecast_data import _monday

    this_monday = _monday(as_of)
    mondays = [this_monday - timedelta(days=7 * i) for i in range(1, n_weeks + 1)]
    have = {
        r[0]
        for r in session.execute(
            select(StockpileInventorySnapshot.snapshot_date.distinct()).where(
                StockpileInventorySnapshot.snapshot_date.in_(
                    [m.isoformat() for m in mondays]
                )
            )
        )
    }
    return [m.isoformat() for m in mondays if m.isoformat() not in have]
```

`collect_alerts` 中按既有告警条目结构加一项（字段名照同函数现有条目抄）：

```python
    missing = _missing_monday_snapshots(session, as_of)
    if missing:
        alerts.append(
            {
                "key": "missing_monday_snapshot",
                "level": "warning",
                "message": f"缺周一库存快照: {', '.join(missing)}（削弱缺货修正 RL-10）",
            }
        )
```

测试加在 `tests/test_replenishment_redlines.py` 末尾：

```python
class TestRL10MissingSnapshot:
    def test_rl10_missing_monday_snapshot_detected(self):
        import datetime as dt

        from app.repositories import stockpile_db
        from app.services.alerts import _missing_monday_snapshots

        with stockpile_db._session() as s:
            # 空表 → 最近 4 个周一全缺
            missing = _missing_monday_snapshots(s, dt.date(2026, 6, 11), n_weeks=4)
        assert len(missing) == 4
        assert "2026-06-08" in missing
```

- [ ] **Step 3: 跑测试 + Commit**

Run: `pytest tests/test_replenishment_redlines.py tests/ -q -k "alert"`
Expected: 全 PASS

```bash
git add -A && git commit -m "feat(alerts): 预测过期 + 周一快照缺失巡检 (RL-9/RL-10)"
```

---

### Task 9: 全量验证 + 部署衔接

- [ ] **Step 1: 红线文件零 skip 确认**

Run: `pytest tests/test_replenishment_redlines.py -v`
Expected: 全 PASS，**0 skipped**（19 个 skip 全部解除）

- [ ] **Step 2: sqlite 全量 + PG 双腿**

```bash
pytest tests/ -q          # sqlite 快循环
./test.ps1                # 本地 PG + xdist（合并前必过）
```

Expected: 双腿全绿

- [ ] **Step 3: 本地真实数据 sanity（不动线上）**

```bash
# 本地 PG（已镜像线上），跑一次 refresh + 抽查推荐量
$env:DATABASE_URL = 'postgresql+psycopg://dev:devpass@localhost:5433/label_sync'
python -m alembic upgrade head
python -c "from app.services.forecast import refresh_forecast_output; print(refresh_forecast_output())"
```

人工抽查 restock 页 5-10 个 SKU：
- 在途大单覆盖的 SKU（459 个之一）推荐应明显下降/归零（RL-2 生效）
- 间歇 SKU 的 p98 档推荐应比修复前低（RL-1 生效）
- 微小缺口 SKU 推荐显示 0（RL-8 生效）

- [ ] **Step 4: 文档同步**

- `docs/adr/0001-replenishment-policy.md` Status 改 `Accepted`（用户批准后）
- `docs/data-analytics-overview.md` 补 restock 段（引 ADR；附录耦合 1 标注已消除）
- 前端如需展示 `sanity_flag` / `on_order` → 单独小 PR，不混入本次

- [ ] **Step 5: PR**

分支 squash merge 回 main（项目惯例）。PR 描述必须包含：
"推荐量普遍下降是 RL-1 修复 + H=5周(L=4) 的预期结果（旧口径 = 数学性高估 2-3 倍
× 8 周 target），不是回归" + ADR 链接。lead time 已校准（4 周，2026-06-11）。
合并后线上跑一次 `refresh_forecast_output`（或等周刷 cron）。

---

## 任务依赖

```
Task 1 (horizon_quantile) ──┐
Task 2 (RL-4 收缩)          ├─→ Task 6 (schema+refresh) ─→ Task 7 (restock 收口) ─→ Task 9
Task 3 (on_order)  ─────────┤                        ↗
Task 4 (RL-3 剔除) ─────────┘          Task 8 (巡检) ─┘（独立，Task 9 前完成即可）
Task 5 (lead time) ─────────→ Task 6
```

Task 1-5 相互独立可并行；Task 6 依赖 1/4/5；Task 7 依赖 3/6；Task 8 独立。
