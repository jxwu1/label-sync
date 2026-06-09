# 缺货修正信号（第一期）设计

**日期**: 2026-06-09
**状态**: 待用户复核
**关联**: `docs/superpowers/plans/2026-05-12-forecast-and-backtest.md` §1.4 stockout_adjust（原 defer）；Codex 审查 backlog 第 2 期 A；`project_codex_review_backlog` 记忆

---

## 1. 背景与问题

预测的需求序列里，某周「销量 = 0」有两种完全不同的含义：

- **没人买**（真零需求 / 真滞销）—— 该降低需求、降低补货优先级
- **没货卖**（缺货导致零销）—— 需求被库存压抑，**不应**当成滞销，否则越缺货越不补，恶性循环

当前系统无法区分两者。具体两处受影响：

1. **置信度分层**（`forecast_eval.confidence_tier`）：`zero_weeks_last8 >= 6` 触发降级。缺货导致的零销周被一并计入 → 缺货 SKU 被误判"近期零需求"而降级。
2. **补货页**：操作员看到某 SKU 近期零销，无从判断是真滞销还是自己没货，决策缺依据。

`§1.4 stockout_adjust` 当初 defer 的唯一原因是"无 SKU 级库存快照表"。该前置**现已就绪**：`StockpileInventorySnapshot` 表，周一 cron 写全量 `snapshot_date` + `qty_total`，保留历史。

## 2. 范围（第一期）

分期推进，**本期 = 补货侧信号**，并把"缺货周判定"做成可复用纯函数地基，供第二期需求清洗接入。

**本期交付**：
1. 缺货周判定纯函数（地基，第二期需求清洗复用）
2. 近 8 周零销周拆分为「缺货零销 / 有货零销」
3. 置信度降级改用「有货零销」周数（缺货零周不降级）
4. 补货页对「近期零销疑因缺货」SKU 加视觉标记

**本期不做**（第二期及以后）：
- 需求清洗 / base_demand 插补（受快照历史仅 ~3 周限制，短期无效，待快照积累）
- 纠正补货 urgency 打分（动核心打分，风险高，本期只动信号侧）

## 3. 关键数据约束（已与用户确认并接受）

库存快照自 **2026-05-20** 才开始积累（约 3 周，7 个快照日，每周一一份）。需求序列回看 52~156 周。

**后果**：`last8`（近 8 周）里只有最近 ~3 周有快照能判缺货，更早 5 周无快照、判不了 → 默认按非缺货处理、照常降级。

**因此修正只在最近 ~3 周生效，随快照逐周积累而逐月增强。** 第一期不指望立刻翻盘大量 SKU；这是"地基慢慢起作用"，符合预期。

## 4. 架构（方案 1：纯函数 + forecast_output 加列，cron 一处算多处读）

数据流：

```
StockpileInventorySnapshot (周一 cron 写)
        │  barcode →(JOIN stockpile)→ product_model → 各 snapshot_date 的 qty_total
        ▼
stockout_weeks(barcode, end_date, weeks)  ── 纯函数，返回缺货周集合 set[周一 date]
        │
        ▼
refresh_forecast_output (cron 周日/每日刷新)
        │  算 stockout_zero_weeks_last8，连同 nonzero_weeks/zero_weeks_last8 一起写
        ▼
forecast_output 表（新列 stockout_zero_weeks_last8）
        │
        ├──→ confidence_tier 降级判定用 (zero_weeks_last8 − stockout_zero_weeks_last8)
        └──→ summary.py 补货汇总多 select 一列 → restock.js 渲染标记
```

被否方案：方案 2（补货页/置信度各自实时算）重复逻辑 + 与 cron 快照不一致；方案 3（存 sku_summary）割裂预测域内聚。

## 5. 详细设计

### 5.1 缺货判定纯函数 — `app/services/stockout.py`（新文件）

> 文件位置说明：当前代码已是 `app/` 包结构（`app/services/forecast.py` 等均在 `app/` 下），CLAUDE.md 里"当前平铺"为文档漂移。本文件落 `app/services/stockout.py`。

```python
def stockout_weeks(
    barcode: str,
    end_date: date,
    weeks: int,
    session: Session | None = None,
) -> set[date]:
    """返回窗口内判定为缺货的周（周一 date 集合）。

    判定口径（用户确认）：某周所在 ISO 周一的快照 qty_total == 0 → 该周缺货。
    - barcode →(JOIN stockpile)→ product_model；快照按 product_model 存
    - snapshot_date 对齐到所在 ISO 周的周一，作为"该周周初库存"
    - 同一周多个快照取该周一当天（或最接近周一）的一条
    - 无快照覆盖的周不进集合（视为非缺货 / 未知，保守）
    """
```

实现要点：
- barcode→model 反查走 `stockpile` 表（快照不含 barcode，见 `StockpileInventorySnapshot` docstring）。
- **多 barcode 同 model**：一个 model 可能对应多个 barcode；快照是 model 级 `qty_total`。本期按 model 级 `qty_total==0` 判缺货（model 全无货 ⇒ 其下所有 barcode 缺货）。这是保守口径，不拆 barcode 级分摊。
- 窗口与 `weekly_demand_series` 对齐：末周 = 含 `end_date` 的 ISO 周，向前 `weeks` 周，周一为周键。
- 只用现有快照，无快照的周一律不判缺货。

### 5.2 零销周拆分 — `app/services/forecast_eval.py`

`demand_history_stats(series)` 现返回 `(nonzero_weeks, zero_weeks_last8)`，保持不变（原义、原签名，不破坏现有调用与测试）。

新增 stockout-aware 计数（独立纯函数，便于 TDD）：

```python
def stockout_zero_weeks_last8(series: dict[date, int], stockout: set[date]) -> int:
    """近 8 周里「需求 ≤ 0 且 该周在缺货集合」的周数 = 缺货零销周数。"""
    last8 = sorted(series)[-8:]
    return sum(1 for w in last8 if series[w] <= 0 and w in stockout)
```

派生约定（全局统一，不存库、用时现算）：
```
in_stock_zero_weeks_last8 = zero_weeks_last8 - stockout_zero_weeks_last8   # 有货零销
```

### 5.3 存储 — `forecast_output` 加列

alembic 迁移新增：
- `stockout_zero_weeks_last8` `Integer NOT NULL server_default '0'`

`app/models.py::ForecastOutput` 加对应 `mapped_column`。

`refresh_forecast_output`（`app/services/forecast.py:116-148`）刷新每个 barcode 时：
1. 已有 `series`（base_demand）→ 算 `sw = stockout_weeks(bc, end_date, weeks, session=s)`
2. `szw8 = stockout_zero_weeks_last8(series_as_dict, sw)`
3. 写入新列。

> 注意：`refresh` 现有 `series` 是 list（`demand_history_stats` 接 list）。`stockout_zero_weeks_last8` 需要 week→qty 映射判周。`_build_series` 内部本有周键，刷新处需保留 dict 形态（或让 `stockout_zero_weeks_last8` 接 `(weeks_list, qtys_list, stockout_set)` 对齐索引）。实现时统一二者口径，plan 阶段细化。

### 5.4 置信度降级修正 — `forecast_eval.confidence_tier`

降级信号当前（记忆/代码）：`zero_weeks_last8 >= _RECENT_ZERO_DOWNGRADE(=6) → 降一级`。

改为基于「有货零销」：
```
in_stock_zero = zero_weeks_last8 - stockout_zero_weeks_last8
if in_stock_zero >= _RECENT_ZERO_DOWNGRADE:
    降一级，reason 记 recent_zero_demand
# 缺货零周不再触发降级；若有缺货零周，reason 附 stockout_suppressed 说明
```

- `confidence_tier` 签名增参 `stockout_zero_weeks_last8: int = 0`（默认 0 → 向后兼容现有调用与测试）。
- `reasons` 可解释："近 8 周 X 周零销，其中 Y 周因缺货不计降级"。
- `_RECENT_ZERO_DOWNGRADE=6` 阈值不变（用户先前定死，>=4 太易误伤间歇 SKU）。

### 5.5 补货页标记

- `app/services/analytics/summary.py:218-236`：`forecast_by_bc` 多 select `ForecastOutput.stockout_zero_weeks_last8`，带进补货行字段（如 `stockout_zero_weeks`）。
- `restock.js` + `_page_restock.html`：当 `stockout_zero_weeks > 0` 渲染 badge，文案 **`⚠ 近 N 周零销疑因缺货`**（N = stockout_zero_weeks）。
- 命名纪律：UI/字段**禁用"断货"**，统一"缺货零销 / 疑因缺货"。

## 6. 测试（TDD，离线 SQLite）

纯函数（不依赖线上）：
- `stockout_weeks`：①有快照且 qty_total==0 → 入集合；②有快照 qty_total>0 → 不入；③无快照的周 → 不入；④周中补货漏判（只看周一）口径核实；⑤多 barcode 同 model → 按 model qty_total 判；⑥barcode 无对应 model → 空集合不报错。
- `stockout_zero_weeks_last8`：近 8 周窗口、缺货∩零销计数、序列短于 8 周边界。
- `confidence_tier`：⑦近 8 周 6 周零销但全是缺货零销 → **不降级**；⑧6 周零销且全有货 → 降级（回归现有行为）；⑨混合（4 有货 + 3 缺货，有货 4<6）→ 不降级。
- 默认参数向后兼容：`confidence_tier` 不传 stockout → 行为同现状（现有测试不改）。

集成 / 回归：
- `refresh_forecast_output` 写入新列非负、与 nonzero/zero 同源。
- 全量 `pytest tests/` 通过（当前基线 1117）。

验收：
- `pytest tests/test_stockout.py tests/test_confidence_tier.py tests/test_forecast_eval.py` 全过
- 本地灌合成快照 + 需求序列，验证一条「缺货零销」SKU 在补货页出标记 + 置信度不降级（本地 PG / Playwright，参照上次 boson 复制走查）

## 7. 命名与文案纪律

- 标识符 `snake_case`，UI 文案中文。
- **禁用"断货"**（无逐日快照证明不了 stockout 全程），统一：缺货零销 / 疑因缺货 / `stockout_zero_weeks_last8`。

## 8. 不在本期范围（YAGNI / 后续）

- base_demand 需求插补（第二期，待快照积累）
- urgency 打分纠正（动补货核心，第二期评估）
- barcode 级库存分摊（本期 model 级保守判定够用）
- 逐日快照 / 周中缺货精度（现 cron 周一一份，够第一期）
