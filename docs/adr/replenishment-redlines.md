# 补货数值退化红线清单

> **Date**: 2026-06-11
> **关联**: `docs/adr/0001-replenishment-policy.md`（决策依据）、
> `tests/test_replenishment_redlines.py`（测试骨架，逐条对应）
> **用途**: 每条红线 = 一种会让补货量算错（负数/爆量/震荡/静默偏差）的具体退化模式。
> 三类条目：**[修复]** 当前就在发生的错误；**[守住]** 当前正确但易被改坏的行为；
> **[监控]** 无法单测、需巡检告警的运行时条件。
> 本清单是 P3（AGENTS.md 蒸馏）的上游：[修复]/[守住] 沉到 pytest 永久执行，
> [监控] 进 cron 巡检，判断模式进 AGENTS.md。

---

## RL-1 [修复] 跨期聚合用 周分位 × N —— 系统性爆量

- **触发条件**: 任何用单周分位数线性放大到多周 horizon 的代码路径。
  现存两处：`restock_calc._restock_recommendation`（`p98 × 8`）、
  `restock_calc.compute_forecast_snapshot`（`quarter_p98 = p98 × 13`）。
- **当前行为**: 8 周需求上限 = 周 p98 × 8。间歇序列（多数周 0、偶发大单）下
  周 p98 被单笔大单顶高，×8 后高估可达 2-3 倍 → 爆仓方向的系统性偏差。
- **期望行为**: H 周需求分位数 = bootstrap（有放回抽 H 个周值求和 × 2000 次）
  的和分位数，固定 seed。数学性质：`Q_α(ΣD) ≤ N × Q_α(D)`（α ≥ 0.5 时），
  间歇序列下严格小于。
- **测试**: `test_rl1_horizon_quantile_below_linear_scaling`、
  `test_rl1_horizon_quantile_deterministic_with_seed`
- **不变量**: `horizon_q98 ≤ weekly_p98 × H`；`horizon_q98 ≥ horizon_q50`。

## RL-2 [修复] 在途量不扣减 —— 重复下单

- **触发条件**: 推荐量计算只减现库存、不减未到货采购量。
  现状：`_restock_recommendation` 只用 `qty_total`。
- **当前行为**: 审计（2026-06-11）显示 4 张在途单 / 64,165 件 / 459 个 SKU
  完全不在计算内。同一 SKU 在到货前的每个盘点周都会被重复推荐。
- **期望行为**: `IP = max(0, qty_total) + on_order`，
  `on_order = Σ(qty_ordered − qty_arrived)`，仅统计 status 不在
  ('cancelled', 'void') 的单。推荐量 = `max(0, S − IP)`。
- **测试**: `test_rl2_on_order_netting`、`test_rl2_void_orders_excluded`、
  `test_rl2_partial_arrival`
- **不变量**: 在途 ≥ 缺口时推荐量 = 0；`qty_arrived > qty_ordered`（超收）
  时该行在途按 0 计，不得为负。

## RL-3 [修复] 缺货周的删失 0 进训练序列 —— 死亡螺旋

- **触发条件**: `_build_series` 直接消费 `weekly_demand_series` /
  `base_demand_view`，缺货周（库存 0 卖 0）与真实零需求周不区分。
- **当前行为**: 缺货 → 0 入训练 → 分位数被拉低 → 推荐更少 → 更缺货。
  正反馈回路，专门惩罚畅销缺货 SKU。
- **期望行为**: `stockout_weeks()` 判定的缺货周从训练序列**剔除**（当缺失，
  不填 0 不插值）。剔除数记入 `forecast_output.stockout_weeks_excluded`。
- **测试**: `test_rl3_stockout_weeks_excluded_from_series`、
  `test_rl3_exclusion_raises_forecast`
- **不变量**: 剔除缺货周后的 p50/p98 ≥ 剔除前（删失只会压低分布）。
- **已知限制**: 快照历史 2026-05-20 起，修正只能向前覆盖；scraper 漏抓周
  → 该周不判缺货（保守方向，见 RL-10）。

## RL-4 [修复] 短序列尾部估计 —— 单笔大单顶满 p98

- **触发条件**: `len(series)` 较小（最低 `_MIN_FIT_WEEKS = 13`）时，
  经验 p98 ≈ max(series)，单笔异常大单直接成为尾部估计。
- **当前行为**: 13 个点的 98 分位就是最大值；该值再被 RL-1 的 ×8 放大。
  两个缺陷相乘 = 最荒谬的推荐值来源。
- **期望行为**: 序列 < 30 周时 p98 用收缩估计：
  `p98_short = min(经验p98, p90 × 1.5)`（p90 在小样本下稳定得多）。
  ≥ 30 周用纯经验分位数。30 与 1.5 为初值，回测验收后固化。
- **测试**: `test_rl4_short_series_tail_shrinkage`、
  `test_rl4_long_series_uses_empirical`
- **不变量**: 任意长度下 `p98 ≥ p50 ≥ 0`。

## RL-5 [守住] 输出不变量 —— 非负与分位单调

- **触发条件**: 任何修改 `ForecastDist` 构造、`_restock_recommendation`、
  凑整逻辑的改动。
- **当前行为**: 正确（`max(0, ...)` clamp 存在，`_round_up_to_pack` 保序），
  但分散在各处、无集中断言，重构易破坏。
- **期望行为**: 永久成立：
  1. `mu, sigma, p50, p98 ≥ 0`
  2. `p50 ≤ p98`
  3. `restock_qty_p50 ≤ restock_qty_p98`（凑整后仍成立）
  4. 凑整只向上且增量 < 1 个中包：`0 ≤ rounded − raw < pack`
  5. `middle_qty ∈ {None, 0, 1}` 时凑整恒等
- **测试**: `test_rl5_dist_invariants`、`test_rl5_recommendation_monotonic`、
  `test_rl5_pack_rounding_bounds`

## RL-6 [守住] 合理性上限闸 —— 无仓容数据下的爆量兜底

- **触发条件**: 单 SKU 单次推荐量异常大（无论上游哪个环节退化导致）。
- **当前行为**: 无任何上限，上游错误直接穿透到采购建议。
- **期望行为**: `推荐量 > max(历史最大单次进货量 × 3, 中包 × 10)` 时不静默输出，
  标记 `sanity_flag = 'exceeds_historical_max'`，前端醒目展示。
  **不自动截断**（截断掩盖上游 bug），只标记。
- **测试**: `test_rl6_sanity_flag_on_extreme_qty`、
  `test_rl6_no_flag_for_normal_qty`

## RL-7 [守住] 负库存（ERP 超卖）按 0 计

- **触发条件**: `qty_total < 0`（ERP 超卖待到货）。
- **当前行为**: 正确 —— `restock_calc.py:197` 与 `stockout.py` 判定口径
  一致（负 = 物理无货）。
- **期望行为**: 维持。`weeks_of_cover` 与 IP 计算中负库存一律 clamp 0；
  缺货判定中 `qty ≤ 0` 即缺货。两处口径必须永远一致。
- **测试**: `test_rl7_negative_stock_clamped`、
  `test_rl7_stockout_criteria_consistent`

## RL-8 [修复] 间歇 SKU 订单 churn —— s/S 退化重合

- **触发条件**: S 很小（周需求 < 1 件）的间歇 SKU，每周 `S − IP` 出现 1-2 件
  微小缺口。
- **当前行为**: 只要差值 > 0 就给推荐 → 每周提示补 1-2 件 → 震荡（要么烦人
  要么训练用户忽略推荐）。
- **期望行为**: 反震荡触发阈值（ADR D6）：
  `触发 ⟺ S − IP ≥ max(1 中包, 0.25 × S) 或 (现库存 ≤ 0 且 S > 0)`。
  不触发时推荐量显示 0（持有），不显示微小缺口值。
- **测试**: `test_rl8_no_churn_below_threshold`、
  `test_rl8_stockout_always_triggers`

## RL-9 [监控] 预测过期消费 —— refresh 失败后用陈旧分位数

- **触发条件**: `refresh_forecast_output` 周刷失败/漏跑，`forecast_output.computed_at`
  过期，restock 页继续无警告地消费旧值。
- **当前行为**: `compute_forecast_snapshot` 返回 `computed_at` 但消费端不检查。
- **期望行为**: `computed_at` 距今 > 14 天 → 巡检告警（接入既有 cron 告警通道）
  + restock 页推荐列标"预测过期"。
- **测试**: `test_rl9_staleness_detection`（纯函数部分）；告警链路走既有
  cron 巡检测试模式。

## RL-10 [监控] 快照缺失周静默削弱缺货修正

- **触发条件**: scraper 某周一未产出快照 → `stockout_weeks` 对该周返回
  unknown → 不判缺货 → RL-3 的剔除对该周失效，无任何信号。
- **当前行为**: 静默（保守方向，预测偏低而非偏高，但削弱删失修正）。
- **期望行为**: 巡检检查最近 N 周的周一快照存在性，缺失 → 告警
  （接入既有 scrape-failure-alert 通道）。
- **测试**: 巡检函数单测 `test_rl10_missing_monday_snapshot_detected`。

---

## 蒸馏指引（P3 消费本节）

**沉到 pytest（确定性，CI 永久执行）**: RL-1 ~ RL-8 全部测试。
**沉到 cron 巡检**: RL-9、RL-10。
**进 AGENTS.md 的判断模式**（无法单测的 review 红线）:
- 任何 PR 改动补货公式/分位数计算 → 必须同步更新本清单 + 对应测试，缺一 reject
- 任何新增"周值 × 系数"形态的代码 → 默认怀疑 RL-1 复发
- 任何新消费 `forecast_output` 的代码 → 检查是否处理 `computed_at` 过期与
  `stockout_weeks_excluded`
- 任何改 `categorizer` 阈值的 PR → 提示回测结果失效需重跑（耦合见 ADR 附录 3）
