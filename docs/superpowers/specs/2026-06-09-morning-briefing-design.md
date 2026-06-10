# 最新批次简报（晨间简报）v1 — 设计

**Date:** 2026-06-09
**Status:** 已批准（2026-06-09）
**Backlog:** 老板 backlog #3（[[project_boss_backlog]]）
**Owner:** jxwu1

---

## 1. 目标与非目标

### 目标
老板早上 **3 分钟读完并形成行动**的入口页。把现有分散信号（销售、补货、缺货、压货、数据新鲜度、采购、异常）聚成 5 张卡片 + 3 个行动列表。优先**信息结构**与**可信口径**，不追求大而全。

**v1 铁律：每个指标都要能一句话解释。解释超过一句话的指标不进 v1。**

### 非目标（v1 明确不做）
- 不做图表（折线/柱状），先做卡片 + 行动列表。
- 不新建 `briefing` 快照表、不加 cron。纯只读聚合现有物化表。
- 不估算缺货损失量。
- 不做数量配置器（列表长度固定）。
- 不改默认登录落页（员工流程不动）。
- 不做自然日/实时语义。

---

## 2. 时间语义（keystone 决策）

底层数据是**周粒度**（scraper 周任务灌 `inventory_events`，freshness 容忍 ~9 天）。系统无日级销售数据。因此：

- 页面叫 **「最新批次简报」**，不叫「今日」。
- 副标题：`截至 <本批次数据周> · 数据刷新于 <imported_at 时间>`。
- 卡片/列表文案禁止「今日销售」「今日必须」，用「本批次 / 当前 / 建议」。

### 「本批次数据周」定义（收紧，不骗人）
- 取 `inventory_events` 中**最新的完整 ISO 周**作为本批次数据周。
- 完整周定义：`week_start + 7 天 <= latest_event_date + 1 天`。
- 若最新周不完整 → 取其**上一完整 ISO 周**。
- 若连一个完整周都没有 → 销售健康卡降级「数据周未完整」，不给环比/预期结论。

---

## 3. 架构（最小改动）

```
GET /briefing          → 页面 (render partial)
GET /briefing/data     → JSON 聚合 payload
```

- **路由蓝图**：新增 `app/routes/briefing.py`，`Blueprint("briefing", url_prefix="/briefing")`，在 `app/routes/__init__.py` 注册。只读，走现有 session auth，**不加 X-Upload-Token**。
- **服务层**：新增 `app/services/briefing.py`，唯一职责 = 调现有服务/物化表拼装 payload。**不写新业务算法、不建表、不加 cron。**
- **前端**：新增 `templates/partials/_page_briefing.html`；侧栏**置顶**新增导航项「最新批次简报」（`nav` store + index 注册）。
- **数据源全部复用**（已核实存在）：

| 信号 | 复用 |
|---|---|
| 数据新鲜度 | `app/services/analytics/freshness.py::get_data_freshness()` |
| SKU 汇总（库存/销速/可售周数/补货量/缺货周/成本值） | 物化表 `sku_summary` via `app/services/analytics/summary.py` |
| base_demand 实际周需求 | `app/utils/forecast_data.py::base_demand_view(barcode, end_date, weeks)` |
| 下期预测 p50 | `forecast_output` 表 / `ForecastOutput` 模型（最新快照 p50/p98） |
| 模型校准 bias | `backtest_results` / `app/services/forecast_eval.py` |
| 补货抑制 | `app/services/restock_decisions.py::list_suppressed()` |
| 采购订单 | `app/services/purchase.py::list_orders()` + `compute_supplier_lead_times()` |
| 数据异常 | `app/services/data_quality.py::build_report()` |

---

## 4. 五张卡片（精确口径）

### 卡片 1：本批次销售健康
**主口径（B）= 本批次完整周 base_demand Σ vs 上一完整周 base_demand Σ**，显示涨跌量 + 涨跌%。
- 实际口径复用 `base_demand_view()` 的清洗后周需求（已过滤大单/批发、退货归并、客户过滤），仅覆盖 retail_dominant/mixed SKU。两周用**同一 SKU 集合**求和。
- **副信息（只展示，不相减）**：
  - `forecast_output.p50` Σ → 标「下期系统预期：约 N 件」。
  - backtest bias → 标「模型近期校准：回测中整体偏高/偏低 X%」。

文案示例：
> 本批次清洗后销量较上批 **+12%**
> 下期系统预期：约 380 件 · 模型近期校准：回测整体偏高 6%

**降级**：
- base_demand 覆盖 SKU 太少（< 阈值，v1 取覆盖 SKU 数 < 5）→ 显「销售口径覆盖不足」，不给结论。
- 上一完整周无数据 → 只显本批次 base_demand 总量，不给涨跌。
- `backtest_results` 为空 → 不显模型校准行。

**明确禁止**：
- ❌ 不做「本批次实际 vs `forecast_output.p50`」的偏差结论。
- ❌ `forecast_output.p50` 只能叫「下期预期」，不能叫「本批次预期」。

### 卡片 2：当前补货风险
需补货 SKU 数（`sku_summary` 中 `restock_qty_p50 > 0` **且未被 skip 抑制**，扣除 `list_suppressed()`）。
- 拆两档：**紧急**（可售周数 `weeks_of_cover ≤ 阈值`，v1 取 ≤ 2）/ **一般**。
- 一句话：「N 个 SKU 建议补货，其中 M 个紧急（可售 ≤ 2 周）」。

### 卡片 3：疑似缺货影响
`sku_summary` 中 `stockout_zero_weeks_last8 > 0` 的 SKU 数。
- 一句话：「N 个 SKU 近期零销疑因缺货，补货后销量或恢复」（区别于有货卖不动）。
- v1 **不估损失量**。

### 卡片 4：当前压货风险
dying/declining 且有库存（`current_stock > 0`）的 SKU 数 + 库存量合计。
- **有成本数据**（`sku_summary.inventory_cost_value_eur` 非空）→ 加显压货金额 Σ（库存×成本）。
- **优雅降级**（本地 PG 成本列空、线上待确认，见 [[project_local_pg_derived_cols_empty]]）：成本全空 → 只显 SKU 数 + 库存量 + 标「无成本数据」，并在数据新鲜度卡提示成本覆盖率。
- ❌ 不用虚假默认成本。
- 一句话：「N 个滞销/呆滞 SKU 仍有库存（合计 X 件 / €Y）」。

### 卡片 5：数据新鲜度
复用 `get_data_freshness()`：数据日期 / 距今天数 / stale 标志 / 抓取成功状态。
- 加显**成本覆盖率%**：分母固定 = `sku_summary` 当前返回的全部 SKU 数（非「有库存 SKU」），分子 = 其中成本非空的 SKU 数。呼应卡片 4 降级。
- stale（> 9 天）→ 红条「数据已超过 N 天未刷新」。空库不报红。

---

## 5. 三个行动列表（默认 Top 5 + 「查看全部 →」深链）

| 列表 | 数据源 | 排序 | 行内容 | 深链 |
|---|---|---|---|---|
| **建议补货** | `sku_summary`（未抑制、`restock_qty_p50>0`） | 可售周数升序，平手按建议量 p50 降序 | 型号 / 库存 / 周销速 / 建议量(p50) / 可售周数 | `/restock` |
| **建议催/确认** | `purchase.list_orders()` 中 `status='placed'`（未到货未作废） | 逾期天数降序；逾期 = 今天 > 下单日 + 该供应商 `compute_supplier_lead_times()` 中位前置期；无前置期数据则下单日最久优先 | 供应商 / 数量 / 下单日 / 逾期天数 | `/purchase` |
| **建议复查异常** | `data_quality.build_report()` 各类异常 | 数量降序 | 异常类型 / 数量 / 样例 | `/data_quality` |

**采购数据说明**：`purchase_orders` 表存在（`order_date`/`arrival_date`/`status` placed/arrived/void）。`arrival_date` 仅在 `record_arrival()` 时写入（实际到货），pending 订单无「预计到货期」前向字段，故逾期用「下单日 + 供应商中位前置期」推算，诚实可解释。
**降级**：`purchase_orders` 空表 → 列表显「暂无采购订单」，不阻塞页面。**不**从散乱事件硬推「已下单未到货」。

**深链范围约束**：「查看全部」若目标页当前不支持过滤参数，v1 **至少跳到对应模块即可**，不为深链临时扩范围改三套现有列表页（`/restock` `/purchase` `/data_quality`）。

---

## 6. 错误处理 / 隔离（区分业务块 vs 系统级）

- **业务信号失败**（某卡片/列表取数抛错）：`200` + 该 block `ok=false` + `error` 摘要；前端该块显「暂不可用」，**不拖垮整页**。
- **系统级失败**（DB 连接失败 / session/auth 异常 / schema 缺列）：返回正常 HTTP 错误码（5xx/4xx），**不伪装成 200**。
- `/briefing/data` 顶层 payload 结构：

```json
{
  "ok": true,
  "generated_at": "2026-06-09T13:40:00",
  "data_week": "2026-06-01",
  "data_week_complete": true,
  "freshness": { "stale": false, "days_since": 1, "...": "..." },
  "cards": {
    "sales_health": { "ok": true, "...": "..." },
    "restock_risk": { "ok": true, "...": "..." },
    "stockout_impact": { "ok": true, "...": "..." },
    "overstock_risk": { "ok": true, "cost_available": false, "...": "..." },
    "data_health": { "ok": true, "...": "..." }
  },
  "actions": {
    "restock": { "ok": true, "items": [], "total": 0 },
    "follow_up": { "ok": true, "items": [], "total": 0 },
    "review_anomalies": { "ok": true, "items": [], "total": 0 }
  }
}
```

- 空库（无 `inventory_events`）→ 友好空态，不报红。

---

## 7. 性能

- 全部读物化表 `sku_summary` + 单次 `forecast_output` / `backtest_results` / `data_quality` / `purchase` 查询，无全表重算。
- 销售健康的 `base_demand_view()` 仅对**有 forecast 覆盖的 SKU 集合**循环两周（本批次周 + 上一完整周），范围可控；如循环过大，限定到 forecast_output 中 retail_dominant/mixed 的 barcode 集合。
- 验收目标：`/briefing` 加载 < 1s。
- **销售健康单独抗风险**：把销售健康做成独立可测函数（`compute_sales_health()`），plan 中记录测试数据规模；若 `base_demand_view()` 两周循环导致整页超时，**v1 允许该卡降级为「销售健康暂不可用」**（block `ok=false`），不拖慢整页其余卡片。

---

## 8. 测试

`tests/test_briefing_service.py`（conftest 临时 sqlite 隔离种子，**绝不碰真实库**，见 [[feedback_worktree_not_isolate_db]]）：
- 每张卡片正常口径单测。
- 降级路径：销售口径覆盖不足 / 上一完整周无数据 / backtest 空 / 成本全空 / 空库 / 数据周不完整 / 采购空表。
- 错误隔离：某信号抛错 → 该 block `ok=false`、其余正常、整体 200。
- 「本批次完整周」选取逻辑单测（含最新周不完整→退上一完整周）。
- 补货列表排序（可售周数升序）+ skip 抑制扣除。
- 催/确认逾期排序（含无前置期回退下单日）。

路由烟雾：`/briefing` 200；`/briefing/data` 顶层结构 + 各 block 标志；系统级失败返回非 200。

---

## 9. 验收标准

1. `/briefing` 页面加载 < 1s（复用物化表，不全表重算）。
2. 5 张卡片口径与 §4 一致，每个能一句话解释。
3. 销售健康卡：主显 base_demand 环比；副显「下期系统预期」与「模型近期校准」，**不做 actual vs p50 偏差结论**。
4. 3 个列表各默认 5 条、按规定排序、「查看全部」跳对页。
5. 成本全空 → 压货卡降级数量版 + 标「无成本数据」；预测覆盖不足 → 销售卡不给结论；采购空表 → 催/确认列表「暂无采购订单」。
6. 业务块失败显「暂不可用」不白屏；系统级失败返回正确 HTTP 错误码；空库友好空态。
7. 副标题正确显示本批次数据周 + 刷新时间；stale 红条。
8. 侧栏置顶新增「最新批次简报」，默认登录落页不变。
9. 全量 `pytest tests/` 通过。

---

## 10. 风险与待确认

- **线上成本列是否真有数据**未确认（[[project_local_pg_derived_cols_empty]]）；本地必走降级路径开发，线上覆盖率由卡片 5 实时暴露。
- `arrival_date` 双语义（仅实际到货写入）→ 逾期靠供应商中位前置期推算，属估算，文案标「按前置期推算」。
- v1 验证老板页信息结构是否有用；稳定后再议是否沉淀 briefing snapshot 表 / 设为老板默认首页。
