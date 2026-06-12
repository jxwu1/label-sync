# Plan: 回测审计修复第一批 — LK-1 时间上界 + MASE 标准化 + 重跑刷新

> **Date**: 2026-06-12
> **执行者**: Opus（plan 作者 Fable 5，按 docs/plan-templates.md T1 风格）
> **上游**: `docs/thesis/回测方法论审计-2026-06-12.md` 第五节修复清单 #1/#2/#5
> **为什么是这三个**: 论文（周一 2026-06-15 开工）引用的 MASE/coverage 数字
> 依赖 #2 完成后的重跑；#1 是 #2 重跑前必须修的泄漏（否则重跑数字还是旧口径）；
> #5 与重跑同车顺手。**#3（coverage_nonzero）/#4（coverage_h4）不在本 plan**，
> 独立成篇免互相阻塞。

## 前置检查（不过门不动手）

- [ ] 读审计 LK-1 / MT-1 / SN-2 三节全文（机理 + 影响评估）
- [ ] 读 AGENTS.md Review 红线 D1/D2（改公式必须三件套同步 + 数值测试全绿）
- [ ] 确认本地 PG 已镜像线上（重跑在本地做，**不在生产跑**；
      生产长任务期间禁 push main —— 反例库 E10）
- [ ] `git log --oneline -3` 确认基于最新 main

## Task 1 — LK-1：分类与清洗加 as_of 时间上界（审计 #1）

**改动点**（全部加可选参数，生产调用传 today 行为不变）：

1. `app/utils/categorizer.py::_fetch_sku_doc_net_qty(barcode, session, as_of=None)`
   与 `_fetch_last_sale_at(barcode, session, as_of=None)`：
   `as_of` 非 None 时查询加 `event_at < cutoff`。
   **cutoff 定义 = `_monday(as_of) + 7 天` 的 isoformat**（与
   `weekly_demand_series` 的 `window_end_exclusive` 同一周界语义，单源；
   生产 as_of=today 时未来事件不存在，行为不变）。
2. `classify_sku_type` 把自己的 `as_of` 透传给两个 fetch。
3. `app/utils/forecast_data.py::base_demand_view`：IQR stats 的
   `_fetch_sku_doc_net_qty(barcode, session)` 调用补 `as_of=end_date`。
4. **bulk 路径同步**（反例 E5，三处实现）：`base_demand_views_bulk` 的
   ①last_sale 查询 ②doc_nets 查询，同样加 cutoff —— 漏掉任何一个，
   bulk/单 SKU 等价测试会红（这正是它存在的意义）。

**verify**:
- 新回归测试 `tests/test_categorizer_asof.py`：构造"cutoff 之后才出现大单/
  销售"的 SKU，断言 ①分类不被未来改写 ②IQR 阈值不含未来 doc
  ③`as_of` 在过去时 dying 判定不被未来销售复活
- `pytest tests/test_model_routing.py tests/test_forecast_bulk.py
  tests/test_briefing*.py` 全绿（bulk/单 SKU 等价仍成立）
- `pytest tests/` 退出码 0

## Task 2 — MT-1：MASE 改标准定义（审计 #2）

**现状**：`backtest.mase(actual, predicted)` 分母 = 展平 records 序列的
lag-1 差分（同周重复 4 次 + 跨窗跳变，无统计语义）。

**目标**（Hyndman & Koehler 2006）：分母 = **训练集 in-sample one-step
naive MAE**。expanding window 下逐窗定义：

```
对 walk_forward 的每个窗 w（train_w = series[:cut_w]）：
  denom_w = mean(|train_w[i] - train_w[i-1]|)   # in-sample lag-1
  该窗每条 record 的 scaled error = |actual - predicted| / denom_w
SKU 级 MASE = 全部 scaled error 的均值
denom_w == 0 的窗剔除；全部窗都为 0 → MASE = None（沿用现有 None 语义）
```

**实现约束**：
- `walk_forward_backtest` 的 records 增加 `train_naive_mae` 字段（每窗算一次），
  `run_backtest_for_sku` 据此算 MASE；旧 `mase()` 函数**删除或改名 `_legacy_rmae`
  并停止调用**（不许双口径并存——反例 E5）
- `forecast_eval.beats_naive_pct` 消费的是存库 mase 列，语义自动随新口径，
  无需改；dashboard 文案若有"MASE"解释处补一句标准定义
- **不碰** `horizon_quantile` / restock 任何逻辑（红线 A 区不在本 plan 范围）

**verify**:
- 手算单测：固定 6 周序列 + 已知模型输出，纸面算出 MASE 期望值，
  `tests/test_backtest_service.py` 增补断言（精确值，不是范围）
- 边界单测：常数序列（denom 全 0）→ None；单窗序列
- `pytest tests/` 全绿 + golden 快照不动（MASE 不影响模型预测输出本身——
  若 golden 变红说明改过界了，停下来）

## Task 3 — SN-2：入选过滤只数训练可用段（审计 #5）

`run_backtest_for_sku`：`nonzero` 统计范围从整条 series 改为
`series[: len(series) - window_test]`（测试期销量不再决定该 SKU 是否入选）。

**verify**: 构造"训练段稀疏、测试段爆发"的序列，断言被排除；
反向（训练段达标、测试段归零）断言仍入选。

## Task 4 — 全模型重跑 + 引用值刷新

1. 本地 PG（生产镜像）跑 6 模型 × base_demand 视图 + NaiveSeasonal52W
   补一条 view=all（ADR-0001 D7 口径），notes 标 `audit-fix-rerun-2026-06`
2. 产出 `docs/backtest-results-2026-06-<日期>.md`：新旧口径对照表
   （旧 run 44 数字保留并标注"旧 MASE 定义，不可与文献对标"）
3. ADR-0001"回测事实"节、ADR-0002 F2/F3 引用值加注记（旧数字不删，
   加"2026-06 修正口径后为 X"）；`docs/thesis/回测方法论审计-*.md`
   第五节 #1/#2/#5 打勾
4. **重跑后置信分层会整体移动**（tier join 最新 prod run）——PR 描述里
   说明这是口径修正不是回归

**verify**: 对照表里 6 模型相对排序与 run 44 一致（审计预言：分母与模型
无关，排序不变——若排序翻了，先怀疑实现错了再怀疑审计错了，都查）；
`./test.ps1` 全绿后再合并

## 波及与失效声明

- 查 `docs/system-mental-model.md` §五"categorizer 阈值"行（Task 1 触 C3/C5）
  与"_restock_recommendation 公式"行（本 plan **不触**，verify 含 golden 不动）
- 历史 backtest run（≤ #44 口径）与新 MASE 不可比，文档逐处标注
- 论文第 5/6 章引用数字统一切新口径（与用户确认章节稿状态后再动论文文件）

## 完成定义

四个 Task 全部 verify 过 + CI 双矩阵绿 + squash merge + 审计文档打勾 +
`project_fable_distill_plan` 记忆更新（若由 Claude 收尾）。
