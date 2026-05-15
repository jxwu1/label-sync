# 预测算法 + 回测框架 plan

**起草日期**：2026-05-12
**最近更新**：2026-05-14（数据已灌库 + 可回测 SKU spike + outlier 摸底，阶段 1 待办大改）
**状态**：进行中（数据回填 pipeline + DB 灌库已 ship；阶段 1 摸底完成，下一步开 1.0 数据预清洗）
**关联设计文档**：`C:\Users\jxwu2002\Desktop\销售分析与补货系统_设计文档.md`
**关联 plan**：`2026-04-28-roadmap.md`（总 roadmap）

---

## 一、背景

按设计文档落地"模块 2 需求预测引擎 + 回测机制"。模块 3 补货决策本轮不做。

**数据现状（2026-05-14 更新，灌库后）**：

| 项 | 实测 | 影响 |
|---|---|---|
| ~~DB 销售（旧）~~ | ~~2025-01-03 → 2026-05-06，194,524 行~~ | 已 wipe 重灌 |
| **DB 销售（新）** | **2023-01-03 → 2026-05-13，1,338,315 行，30,370 SKU** | 跨过 104 周硬门槛 |
| **DB 采购（新）** | **2023→2026-05-13，22,750 行（parquet 直供）** | 阶段 3 LT 可探索（但仍单时间戳） |
| 客户分类 | 4 类（foreign 3243 / chinese 373 / mixed 44 / unknown 6），无 cn_replenish/cn_bulk | 基础需求视图缺一层 |
| SKU 级日库存快照 | ❌ 不存在 | 缺货修正缺基础 |
| 采购双时间戳（下单 vs 到货）| ❌ 单时间戳 | LT 无法实测，本轮不依赖 LT |

**可回测 SKU 现状（2026-05-14 spike）**：

| min_weeks 阈值 | ALL customers | FOREIGN only |
|---|---|---|
| ≥ 20 周 | 17,745 SKU（58%） | 3,970 SKU（14%） |
| ≥ 52 周 | 5,527（18%） | 291（1%） |
| ≥ 104 周（季节项门槛） | **402（1.3%）** | 9 |

空周率：ALL median **73%**，FOREIGN median **90%** → 极稀疏，间歇需求特征。

**关键决策**：用户实际有 2023→现在 3 年完整 sale/purchase 数据，HTML 下载慢没传，
正在通过 parquet 抓取脚本回填。HTML 仍是日常增量主路径，parquet 是一次性历史
回填工具。

---

## 二、已完成

### 2026-05-13：数据全量灌库

- `wipe_events.py` 清空旧 DB（保留 stockpile 主档 + manual_grade/category）
- 销售 parquet `events_sale_2023-01-01_2026-05-13.parquet` 清洗 + 导入 → 1,338,315 行
- 采购 parquet `events_purchase_2023-05-13_2026-05-13.parquet` 清洗 + 导入 → 22,750 行
- 风险表里"采购未抓"和"销售 HTML 抓取慢"两条 🔴/🟡 全部解除

### 2026-05-14：阶段 1 摸底 spike（不进正式文件）

- `_scratch/spike_backtestable_skus.py`：可回测 SKU 数量 / 空周率 / Top100 周均量
- `_scratch/spike_outlier_units.py`：Top10 SKU 原始 qty 分布

**关键发现**：

1. Top10 SKU 的 8640/4320/1440 **不是单位混乱**，是真大批发订单（希腊 wholesale 客户 `ANTONIOY NIKH` / `ΔΗΜΗΤΡΙΟΣ ΜΕΡΤΙΚΑΣ`），qty 是 12/24/144 倍数（一打/盒/箱）
2. **SKU 分三类**：A 纯大批发（零零售样本，订单数 1-6，全 ≥720）/ B 批发主导混零售 / C 零售为主混偶发大单
3. **负数 qty 出现**（退货/红冲，例如 `5203692253593` min=-48）—— plan §1.1 直接 `SUM(qty)` 会被退货抵消进周需求，**是 bug**
4. 空周率 mean 70%，>50% SKU 空周 >75% → 间歇需求特征显著，原 plan baseline 三件套（Naive 系列）不够，需补 Croston 类
5. 季节项基本用不上：只有 402 SKU 满足 104 周（1.3%），HW 带季节降级到"少数 SKU 跑"

### 2026-05-12：ETL pipeline 全套（数据回填用）

| 文件 | 用途 |
|---|---|
| `tools/wipe_events.py` | 精确清空 DB（保留 stockpile 主档 + manual_grade/category），dry-run + 强确认 + 自动备份 |
| `etl/parquet_cleaner.py` | 清洗核心 pure function：剔税行 + 剔拼接条码 + 剔重复 + 拆内部账户 |
| `etl/parquet_importer.py` | parquet → DB 核心：按 event_type 拆 sale/purchase 两批，复用 inventory_importer.import_events |
| `tools/clean_parquet.py` | 清洗 CLI（单文件 + 批量 glob） |
| `tools/import_parquet.py` | 导入 CLI（单文件 + 批量 glob） |
| `tests/test_parquet_cleaner.py` | 15 个单测 |
| `tests/test_parquet_importer.py` | 13 个集成测试 |

**清洗规则**（在 1 年真实样本 304,507 行上验证）：

- 剔税行 `90000000001`：84 笔
- 剔拼接条码 `len>=15`：2 笔
- 完全重复行：1 笔
- 内部账户 `999*` → 单独 archive：14,750 笔（4.9%）
- 最终 cleaned: 289,670 行
- 还剩 1 笔 irregular barcode `RDDT2021`（保留进 DB，仅提示）

**完整 pipeline（3 年数据抓完后用）**：

```bash
python tools/wipe_events.py
python tools/clean_parquet.py "raw/*.parquet" --out-dir cleaned/ --archive-dir archive/
python tools/import_parquet.py "cleaned/*.parquet"
python tools/inventory_admin.py stats
python tools/inventory_admin.py verify
```

---

## 三、待办

### 阶段 0：先决事项（并行启动）

- [ ] 0.1 解决 2023-2024 HTML 抓取速度问题（用户进行中）
- [ ] 0.2 32 个 mixed customer 手工归类（数据回填后再做）
- [ ] 0.3 采购导入流程加 `po_ordered_at` 字段（影响模块 3 LT，本轮不阻塞）
- [ ] 0.4 stockpile / supplier 加 `source_country` 列（影响 LT 默认值，本轮不阻塞）

### 阶段 1：预测数据底座（3-4 天，原 2-3 天因 spike 发现的复杂度上调）

新建 `forecast_data.py` + 修 `categorizer.py`：

#### 1.0 数据预清洗 + SKU 类型标注（新增，必须最先做）

- [x] 1.0.1 退货归并 ✅ 2026-05-14 ship（`forecast_data.weekly_demand_series`，12 单测过，commit `0bd96d2`）
- [x] 1.0.2 `categorizer.classify_sku_type` ✅ 2026-05-14 ship（19 单测过 + 真 DB 5/5 退场 OK）
  - 阈值经 spike 1.0.3 验证：qty≤24=零售；wholesale_only=零售<5 笔 或 <5%；retail_dominant=≥80%；其余 mixed
  - 全量 DB 分布：85.8% retail_dominant / 13.2% wholesale_only / 1.0% mixed
- [x] 1.0.3 spike ✅ 2026-05-14（`_scratch/spike_sku_type_thresholds.py`，无需调阈值）
- [x] 1.0.4 加 `dying` SKU 类 ✅ 2026-05-15（4 baseline 全量 backtest 后发现 CrostonSBA Bias=+0.89 系统性偏差）
  - 判定：最后销售距 `as_of` >= 13 周（1 季度）→ `dying`，优先级高于 wholesale_only
  - 阈值经 spike `_scratch/spike_dying_threshold.py` 选定，3 个 Top over-forecast SKU 全部标对
  - `base_demand_view` / `_build_series` 都加 dying 早退路径，dying SKU 不进回测
  - 全量分布：N=13 周阈值会标 46.3% SKU 为 dying（含原本 retail/wholesale 中已停售的）

**verify**：✅ 全过

#### 1.1 周聚合（订正）

- [ ] `weekly_demand_series(barcode, end_date, weeks)` 周聚合销量，空周补 0；**应用 1.0.1 退货归并后再聚合**

#### 1.2 base_demand_view ✅ 2026-05-14

- [x] `base_demand_view(barcode, end_date, weeks)` → `{sku_type, series, exclusion_count, exclusion_qty}`
- 分流:
  - `wholesale_only` / `unclassified`: `series=None` (不进时序预测; wholesale_demand_view 经验分位数路径留待阶段 2 与 backtest 一起做)
  - `retail_dominant`: 仅 `is_bulk_order` 剔单笔异常
  - `mixed`: 同上 + 客户类型过滤 (保留 `foreign` + `chinese`, 剔 `unknown` / `mixed`)
- 实战数据验证: `5203692253593` 剔 19 doc / 2521 qty; `9000000000063` 剔 50 doc / 3019 qty
- **客户过滤简化决策**: plan 原文"保留 foreign + 非 wholesale 客户"但 DB 无 wholesale 客户标签 (希腊大批发也是 customer_type=foreign), 简化为剔 unknown/mixed; 真正剔大单还是靠 is_bulk_order

#### 1.3 winsorize ✅ 2026-05-14

- [x] `winsorize(values, q=0.95)` 顶部 q 分位以上压到 q 分位本身
- 应用范围: 由 §1.2 base_demand_view 决定 (只对 retail_dominant/mixed)

#### 1.4 stockout_adjust 🟡 defer

- **状态**: 阻塞中 — 需先建 SKU 级日库存快照表 (plan §四"明确不做")
- 当前 DB 无 stock_history → 函数实现也只能走 fallback (pass-through), 不值得花 PR 时间
- 等模块 3 补货决策开做时, snapshot 表必补, 那时一起做

#### 1.5 is_bulk_order ✅ 2026-05-14

- [x] `compute_doc_qty_stats(net_qtys)` → `{median, q1, q3, iqr}` 或 None (<4 样本)
- [x] `is_bulk_order(qty, stats, k=3.0)` → `qty > median + k·iqr`, 弃用均值

**verify**：

- `pytest tests/test_forecast_data.py` 全过
- ALL 视图 ≥ 1000 个 SKU 能输出非空周序列
- 抽检 5 个 `wholesale_only` SKU：base_demand_view 不返回它们
- 抽检 5 个 `retail_dominant` SKU：剔除单数量 ≤ 0.5% 总销量

### 阶段 2：回测框架（3-4 天）⭐ 核心阶段

新建 `backtest_service.py`：

- [x] 2.1 ✅ 2026-05-14 `ForecastDist` dataclass + `ForecastModel` Protocol
- [x] 2.2 ✅ 2026-05-14 四个 baseline 全部实现 (NaiveMean4W / NaiveSeasonal52W / LinearTrend12W / CrostonSBA)
- [x] 2.3 ✅ 2026-05-14 `walk_forward_backtest(series, model_cls, window_train=13, window_test=4)`
- [x] 2.4 ✅ 2026-05-14 MAPE / Bias / MASE / coverage_p98

**实战验证** (SKU `5203692253593`, 156 周, retail_dominant):

| baseline | MAPE | MASE | Bias | cov@p98 |
|---|---|---|---|---|
| NaiveMean4W | 1.91 | 0.89 | -0.82 | 85.7% |
| NaiveSeasonal52W | 1.87 | 0.88 | -0.62 | 95.2% |
| LinearTrend12W | 2.01 | 0.99 | -1.17 | 89.1% |
| **CrostonSBA** | **1.74** | **0.85** | -1.94 | 94.6% |

CrostonSBA 在间歇序列上最优 (符合 spike 发现"空周率高"); NaiveSeasonal52W cov@p98 最高。
- [x] 2.5 ✅ 2026-05-14 alembic 迁移 `b9e1c4f8a3d2_add_backtest_tables`, head 已升级
- [x] 2.6 ✅ 2026-05-14 `run_backtest_all_skus(model_name, end_date, weeks, view, ...)` 写表
- [x] 2.7 ✅ 2026-05-14 routes 3 个: `POST /analytics/backtest/run` + `GET /analytics/backtest/runs` + `GET /analytics/backtest/results?run_id=N`
- [x] 2.8 ✅ 2026-05-14 双视图框架完成: `compare_run_pair(run_a, run_b)` + `GET /analytics/backtest/compare`
  - 返回 per-SKU MAPE/MASE/coverage 差异 + summary (improved/worsened/unchanged + median_mase_delta)
  - **全量 30k SKU × 4 baseline × 2 view = 8 runs 实战跑**：未在 PR7 内执行 (估算 4 小时)，用户后续手动触发

**`backtest_runs` 表字段**（spike 后初稿）：

- `id` PK / `created_at` / `model_name` / `view` / `window_train` / `window_test`
- `min_weeks` / `n_skus_total` / `n_skus_scored` / `notes`

**`backtest_results` 表字段**：

- `id` PK / `run_id` FK / `product_barcode` / `sku_type` (`retail_dominant`/`mixed`/`wholesale_only`)
- `n_weeks_train` / `n_weeks_test` / `mape` / `mase` / `bias` / `coverage_p98`
- `mean_actual` / `mean_predicted`

**verify**：

- 任一 `retail_dominant` SKU 在 4 个 baseline 上能拿到 MAPE/MASE/Bias/命中率
- `wholesale_only` SKU 不进 backtest（或单独打标走 `EmpiricalQuantile` baseline）
- 双视图回测：能输出"全量 vs base_demand"分数差异表

### 阶段 3：主力预测模型（3-4 天）

新建 `forecast_service.py`：

- [ ] 3.1 引入 `statsmodels` 依赖
- [ ] 3.2 `HoltWintersModel`：自动判要不要带季节项（数据 ≥104 周 + categorizer.is_seasonal）
- [ ] 3.3 `EmpiricalQuantileModel`（Z 类用）：直接对历史取 p50/p98
- [ ] 3.4 σ 用历史残差而非原始 std（细节坑）
- [ ] 3.5 新品规则：`days_since_first_sale < 90` → 用 erp_category 同类目周均值
- [ ] 3.6 注册进阶段 2 回测框架，对比 baseline
- [ ] 3.7 新建 `forecast_output` 表 + 每日刷新脚本

**verify**：每 SKU 有 `mu/sigma/p50/p98/model_used`；回测分数可比

### 阶段 4：Dashboard 集成（2-3 天）

- [ ] 4.1 SKU 详情页"预测分布"卡片
- [ ] 4.2 SKU 详情页"回测历史"小图
- [ ] 4.3 列表页加排序列：上周 MAPE、命中率
- [ ] 4.4 "模型失效"chip：命中率 < 设定 - 5% 自动标

### 阶段 5：数据补齐回归（看阶段 0.1 进度）

- [ ] 5.1 3 年数据导入完成后重跑 `run_backtest_all_skus`，对比导入前后分数
- [ ] 5.2 "数据扩充前后回归报告"
- [ ] 5.3 此时才能可靠用 STL / 带季节 HW

---

## 四、明确不做（V1.5+ 再说）

- 模块 3 补货决策引擎（s/S、压货预警、override_log）
- LT 实测分布统计（数据基础不够）
- SKU 级每日库存快照表（缺货修正先 fallback，模块 3 之前必补）
- 全面重做 categorizer 4 类分类（保留并行）
- 手工标签体系迁移（8 个标签继续用）

---

## 五、关键设计决策记录

### 1. 路线：先 baseline + 回测框架，再 HW（路线 3 → 2 → 1）

理由：回测是 evaluator，没有它做"算法完善"等于盲调。先建评分台代价最低
（1-1.5 周），收益最高。

### 2. 不做严格按文档"模块 1 完整画像 → 再模块 2"

理由：现有 `categorizer.py` 已经在跑 4 类分类，且有 8 个手工标签产生业务价值。
不应推翻。让回测告诉我们哪里需要升级。

### 3. parquet 是一次性历史回填，HTML 是长期主路径

一次性工具放独立文件（`tools/import_parquet.py`），不污染
`tools/inventory_admin.py import-batch` 主 CLI。

### 4. 客户三分类降级处理

文档要求 `foreigner / cn_replenish / cn_bulk`，现状是 `foreign / chinese / mixed / unknown`。
第一轮 cn_bulk 判定改为"本单 qty > 3 × SKU 全局均量"，不依赖客户自身历史，
绕过"鸡生蛋"问题。

### 5. 季节性不可靠期

DB 数据只有 70 周时 STL 跑不起来（需 104 周）。等 3 年数据导入完成后才能可靠。
本轮先做不带季节的 HW + 经验分位数 baseline。

---

## 六、风险

| 等级 | 风险 | 缓解 |
|---|---|---|
| 🟢 | ~~2023-2024 数据导入卡在 HTML 抓取速度~~ | 销售 + 采购 parquet 已直供并灌库（2026-05-13） |
| 🟢 | ~~parquet 回填数据格式跟 2025+ 不一致~~ | 1 年样本 schema 验证已过，全量灌库成功 |
| 🟡 | mixed 客户 44 笔（< 1.5%）未归类 | 数据回填后做手工归类 |
| 🟡 | **退货负数 qty 处理** | 阶段 1.0.1 强制 document_no 内净抵；测试覆盖 |
| 🟡 | **A 类纯批发 SKU 污染回测** | 阶段 1.0.2 SKU 分流；wholesale 走经验分位数 |
| 🟡 | **空周率 mean 70%，间歇需求** | 阶段 2.2 加 Croston/SBA，评分加 MASE |
| 🟢 | 季节项可用 SKU 只 402 个（1.3%） | HW 带季节降级为"少数 SKU 跑"，不影响主流程 |
| 🟢 | statsmodels 引入影响打包大小 | +30MB 可接受 |

---

## 七、操作日志

- **2026-05-12 上午**：摸底 DB 数据现状，发现 DB 销售比 parquet 少一半
- **2026-05-12 下午**：方案 C 精确清空脚本 `tools/wipe_events.py` ship
- **2026-05-12 下午**：清洗层 `etl/parquet_cleaner.py` + CLI ship；15 单测过
- **2026-05-12 下午**：parquet importer `etl/parquet_importer.py` + CLI ship；13 集成测试过
- **2026-05-12 下午**：本 plan 落档
- **2026-05-12 晚**：用户提供 3 年销售 parquet `C:\Users\64474\OneDrive\桌面\events_sale_2023-05-12_2026-05-12.parquet`（14.73 MB）；inspect 通过——951,135 行 / 2023-05-12 → 2026-05-12 / 全 event_type=sale / 月度无缺月 / schema 跟 2025 样本一致
- **2026-05-12 晚**：明确明天动作（见第八节）
- **2026-05-13**：销售 3 年 + 采购 3 年 parquet 全部清洗 + 灌库；DB 总行数 1,361,065（销售 1,338,315 / 采购 22,750），日期 2023-01-03 → 2026-05-13，45,614 SKU
- **2026-05-14 上午**：`_scratch/spike_backtestable_skus.py` 摸底——可回测 SKU 数量 / 空周率 / Top100 周均量
- **2026-05-14 上午**：`_scratch/spike_outlier_units.py` 查 Top10 outlier——确认不是单位 bug 是真大批发，发现退货负数 qty + SKU 分三类
- **2026-05-14**：本 plan 大改——阶段 1 重写（加 1.0 数据预清洗 + SKU 类型分流）；阶段 2 加 Croston baseline + 双视图回测 + 表字段

---

## 八、下一步（2026-05-15 起）

**已完成**（2026-05-13 / 2026-05-14）：

- ✅ 数据灌库（销售 134 万 + 采购 2.3 万行）
- ✅ 可回测 SKU 摸底 spike（→ `min_weeks=20` 确认 / 季节项降级 / 四 baseline / 双视图）
- ✅ Top10 outlier 摸底 spike（→ 真大批发 / SKU 三分类 / 退货负数 qty）
- ✅ Plan 大改（阶段 1.0 新增 + 阶段 2.2 加 Croston + 表字段定）

**下一步动作（按顺序，建议各开独立 PR）**：

1. ✅ **阶段 1.0** (2026-05-14, PR1/PR2 shipped)
2. ✅ **阶段 1.1-1.5** (2026-05-14, PR3/PR4 shipped; 1.4 defer 等库存快照表)
3. ✅ **阶段 2 全部完成** (2026-05-14, PR5/PR6/PR7 shipped)
4. **可选下一步**:
   - 用户实战跑 8 个 full run, 用 `/analytics/backtest/compare` 看 base_demand vs all 实战差异
   - 阶段 3 主力预测模型 (HoltWinters / EmpiricalQuantile / 新品 erp_category 同类目均值)
   - 阶段 4 Dashboard 集成 (SKU 详情页"预测分布"+"回测历史"卡片)
   - 阶段 5 数据扩充前后对比 **已作废**: 当前 DB 已 wipe 重灌, 无"前"数据可比; 改为以本次基准为起点, 后续重要变更后再 snapshot

**仍待澄清**：
- 阶段 4 verify 条件（等阶段 2 出第一份回测结果再定）
- 阶段 5 MAPE 改善阈值（依赖阶段 2/3 的实际基准分）
- mixed 客户 44 笔手工归类（小数量，可与阶段 1.0 并行做）
