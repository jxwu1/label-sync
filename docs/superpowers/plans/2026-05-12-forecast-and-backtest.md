# 预测算法 + 回测框架 plan

**起草日期**：2026-05-12
**状态**：进行中（数据回填 pipeline 已 ship；预测 + 回测 等数据导入后开干）
**关联设计文档**：`C:\Users\jxwu2002\Desktop\销售分析与补货系统_设计文档.md`
**关联 plan**：`2026-04-28-roadmap.md`（总 roadmap）

---

## 一、背景

按设计文档落地"模块 2 需求预测引擎 + 回测机制"。模块 3 补货决策本轮不做。

**数据现状（2026-05-12 摸底）**：

| 项 | 实测 | 影响 |
|---|---|---|
| DB 销售 | 2025-01-03 → 2026-05-06，194,524 行 | 不够 STL 104 周硬门槛 |
| DB 采购 | 2023-01-05 → 2026-05-06，32,937 行 | 但销售对不上 → 用不上 |
| Parquet 样本 1 年 | 2025-05-12 → 2026-05-12，304,507 行 | **DB 比实际数据少 ~50%** |
| 客户三分类 | 4 类（foreign/chinese/mixed/unknown），无 cn_replenish/cn_bulk | 基础需求视图缺一层 |
| SKU 级日库存快照 | ❌ 不存在 | 缺货修正缺基础 |
| 采购双时间戳（下单 vs 到货）| ❌ 单时间戳 | LT 无法实测，本轮不依赖 LT |

**关键决策**：用户实际有 2023→现在 3 年完整 sale/purchase 数据，HTML 下载慢没传，
正在通过 parquet 抓取脚本回填。HTML 仍是日常增量主路径，parquet 是一次性历史
回填工具。

---

## 二、已完成（2026-05-12）

### ETL pipeline 全套（数据回填用）

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

### 阶段 1：预测数据底座（2-3 天）

新建 `forecast_data.py`：

- [ ] 1.1 `weekly_demand_series(barcode, end_date, weeks)` 周聚合销量，空周补 0
- [ ] 1.2 `base_demand_view(barcode, ...)` 基础需求 = 老外 + 中补；订单级判 cn_bulk（本单 qty > 3 × SKU 平均）剔除
- [ ] 1.3 `winsorize(series, q=0.95)` 95 分位压缩
- [ ] 1.4 `stockout_adjust(series, stock_history)` 库存=0 周替换为中位数（fallback：无快照时跳过）
- [ ] 1.5 `is_bulk_order(qty, sku_avg, threshold=3.0)` 异常订单识别

**verify**：`pytest tests/test_forecast_data.py` 全过；至少 100 个 SKU 能输出非空周序列

### 阶段 2：回测框架（3-4 天）⭐ 核心阶段

新建 `backtest_service.py`：

- [ ] 2.1 `ForecastModel` Protocol：`fit(history) → predict(steps) → ForecastDist(p50, p98, mu, sigma)`
- [ ] 2.2 三个 baseline：`NaiveMean4W` / `NaiveSeasonal52W` / `LinearTrend12W`
- [ ] 2.3 `walk_forward_backtest(barcode, model, window_train=13, window_test=4)` 滚动训练/预测/收集
- [ ] 2.4 评分函数：MAPE / Bias / 命中率（actual ≤ p98 占比）
- [ ] 2.5 alembic 迁移：`backtest_runs` + `backtest_results` 两表
- [ ] 2.6 批量入口 `run_backtest_all_skus(model_name, min_weeks=20)` 写表
- [ ] 2.7 routes：`POST /analytics/backtest/run` + `GET /analytics/backtest/results`

**verify**：任一 SKU 在 3 个 baseline 上能拿到 MAPE / Bias / 命中率三个数

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
| 🔴 | 2023-2024 数据导入卡在 HTML 抓取速度 | parquet 回填路径已就绪；算法和导入并行 |
| 🟡 | parquet 回填数据格式跟 2025+ 不一致（旧 ERP 编码不同） | 先抓 1 个月样本验证 schema，再全量 |
| 🟡 | mixed 客户 26k 笔（13.5%）未归类 | 32 个 customer 手工归类 0.5 天，导入后做 |
| 🟢 | statsmodels 引入影响打包大小 | +30MB 可接受 |

---

## 七、操作日志

- **2026-05-12 上午**：摸底 DB 数据现状，发现 DB 销售比 parquet 少一半
- **2026-05-12 下午**：方案 C 精确清空脚本 `tools/wipe_events.py` ship
- **2026-05-12 下午**：清洗层 `etl/parquet_cleaner.py` + CLI ship；15 单测过
- **2026-05-12 下午**：parquet importer `etl/parquet_importer.py` + CLI ship；13 集成测试过
- **2026-05-12 下午**：本 plan 落档

---

## 八、下一步

- **用户**：抓 2023-2024 历史数据（HTML → parquet）
- **Claude（可并行）**：阶段 1（预测数据底座）或 阶段 2（回测框架）—— 等用户拍板
