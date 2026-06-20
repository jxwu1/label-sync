# 补货决策页 Vue 迁移 — Phase 1（只读列表 + 筛选 + 排序）设计

**Date:** 2026-06-20
**Status:** Approved（rev5，2026-06-20 用户批准；含 Phase 1 省略 urgency tooltip + 修复双 null 排序 comparator 两项范围决定）
**Spec 类型:** 前端独立化 §11 高频决策页迁移（补货，紧随货号历史 Phase 4c）
**关联:**
- `docs/superpowers/specs/2026-06-12-frontend-decoupling-design.md` §11（迁移排期 + 新栈只消费 `/api/*` 契约文本）
- `docs/superpowers/specs/2026-06-08-restock-skip-suppression-design.md`（决策回流 / suppressed）
- 现状：`static/js/restock.js`（1310 行）+ `templates/partials/_page_restock.html`
- 模板：`frontend/src/pages/history/`（Phase 4c）；后端瘦端点：`app/routes/history.py`（`bp`+`api_bp` 双蓝图）

---

## 1. 目标与切割线

迁补货页到 `/ui/restock`，分期推进。本 spec 只覆盖 **Phase 1**。

### Phase 1 范围
**只读、且只渲染本期能完整工作的控件**：主列表、`filterPredicate` 全套筛选、排序、KPI（去「已标记」）、供应商概览。后端新增 2 个 strict `/api/restock/*` 瘦端点（契约要求，§3）。

### 明确省略（不渲染，避免「假控件」）
- ⚑ 勾选列、批量栏、智能凑单、撤销
- 「已标记」KPI、`band=flagged`（依赖 selection，只读期恒空）
- 单条 drawer + drawer 操作（`.rs-row` 不加 clickable cursor / 不绑展开）
- **urgency 单元格 tooltip（urgencyTip）**：Phase 1 urgency 列只渲染 bar + 数字，**不带 4 维拆解 tooltip**（拆解随 drawer 进 Phase 2）→ 故 `urgency_breakdown` 不进 RestockItem
- cover 微条 **knob 拖拽**（调 coverThreshold 着色）
- 「安全量」p98 列：**渲染为纯文本**（旧为可编辑 input + editedQty）

### 保留的只读控件
全部筛选 chip（origin 分段 / views 多选 / band：全部·紧急·关注·充足·**已跳过** / cover filter 滑块 / 搜索 / 重置）、排序、货号列→深链 `/ui/history?q=`、cover 微条**静态**着色、marginCell 的 tooltip（用扁平字段，保留）。

**供应商点击进「凑单模式」（第3轮阻断#2，红队 coverMax 静默缩水）**：两处入口——概览 chip（[restock.js:891-893](static/js/restock.js)）**和**表格内 supplier 按钮（[restock.js:1035-1041](static/js/restock.js)）——点击都执行**两个**状态变更：`supplier = X` **且** `coverMax = null`。漏掉 `coverMax=null` 会让默认 `coverMax=4` 继续生效，把该供应商 `weeks_of_cover>4` 的 SKU（如 =8）静默隐藏，凑单行集缩水、违反 1:1。两处入口均加测试。

### 用户可见行为红线
> **本期渲染的控件行为严格 1:1**；省略控件不在红线内（随后续 Phase 迁）。`urgency tooltip` 的省略是本 spec 明列的范围决定，需用户在批准时一并确认。

---

## 2. 关键 1:1 边界（必须只读加载）

旧页默认隐藏 ordered + suppressed。Phase 1 仍必须：
1. 只读 `localStorage["restock_ordered_v1"]`（30 天过期 `loadOrdered` + 货到自动清 `autoClearOrderedByPurchase`，仅写 localStorage）。
2. 只读 `GET /api/restock/suppressed`（失败兜底 `{}`，不阻断主列表）。
3. 「已跳过」band 翻出 suppressed；`days_left` 由后端给 → **前端不需 SKIP_SUPPRESS_DAYS 常量**。

> 双栈期 ordered/suppressed 由旧页写、新页只读消费。

---

## 3. API 契约（第1轮阻断#1 + 第2轮阻断#1）

新栈禁直连旧胖端点。**先投影瘦白名单字段，再 strict 校验**（不设「跳过校验」逃生口；瘦化后 27k 校验成本本就大降）。

**新增（`app/routes/restock.py` 加 `api_bp = Blueprint("api_restock", url_prefix="/api/restock")`，`__init__.py` 注册；实现 `jsonify(RestockItemList.model_validate(payload).model_dump())`）：**

| 端点 | 服务 | schema |
|---|---|---|
| `GET /api/restock/items` | `list_sku_summary()` → **投影到下表白名单** | `RestockItemList { ok:bool, total:int, items:list[RestockItem] }` |
| `GET /api/restock/suppressed` | `restock_decisions.list_suppressed()` | `RestockSuppressedList { ok:bool, items:dict[str, RestockSuppressedEntry] }` |

`RestockSuppressedEntry { skipped_at:str, reason:str|None, days_left:int }`。

### RestockItem 字段白名单（瘦投影 — 全部扁平，无嵌套）
仅 Phase 1 渲染控件消费的字段；`urgency_breakdown` 及 ~15 drawer-only 字段**不含**。**null 契约逐字段对照 service 真实输出锁定**（第3轮阻断#1）——service 恒有非空默认的字段，schema 标**非空**以暴露上游数据错误，不得放宽为可空。证据：`summary.py:305-360`、`restock_calc.py:333-343`。

| 字段 | 类型 | null | Phase 1 消费点 / nullability 证据 |
|---|---|---|---|
| `barcode` | str | 否 | id / search / 深链 / state key |
| `model` | str | 是 | name / search |
| `name_zh` | str | 是 | name / search |
| `origin` | `Literal["FOREIGN","CN","unknown"]` | **否** | filter / originBadge — `classify_origin()`（`app/services/sku_origin.py:27-41`）**只返回这 3 值**（已读源码核实，`classify_origin("HZ001","abc")=="unknown"`）。schema 锁 Literal，**未知值（含 HZ）被 strict 拒绝**；summary.py:375 `origin in ("CN","HZ")` 是 origin 永不为 HZ 的死防御分支，不影响枚举 |
| `supplier_id` | str | 是 | filter / supplier 列 / 概览（`summary.py:358` 可 None） |
| `is_truly_discontinued` | bool | 否 | filter / views / tag / kpi |
| `is_new_item` | bool | 否 | filter / views / tag / kpi（`summary.py:360`） |
| `qty_total` | number | 是 | 库存列（`summary.py:344` `_lookup_qty` 可 None） |
| `weeks_of_cover` | number | 是 | coverCell / filter coverMax / sort（`summary.py:351` 显式 None） |
| `weekly_velocity` | number | **否** | 周销列（`summary.py:320/327` 恒 `0.0` 默认） |
| `weekly_revenue` | number | **否** | 周销额列（`summary.py:321/328` 恒 `0.0`） |
| `margin_pct` | number | 是 | marginCell / sort（`summary.py:367` `float\|None`） |
| `margin_source` | str("master"\|"purchase") | 是 | marginCell tooltip（`summary.py:368` `str\|None`） |
| `margin_price_source` | str("master"\|"events") | 是 | marginCell tooltip（`summary.py:369`） |
| `master_stock_price_eur` | number | 是 | marginCell tooltip / kpi spend 兜底 |
| `master_sale_price_eur` | number | 是 | marginCell tooltip |
| `last_purchase_unit_price` | number | 是 | marginCell tooltip / kpi spend |
| `sale_net_avg` | number | 是 | marginCell tooltip（`summary.py:323/331` None） |
| `weekly_qty_12w` | list[number](len 12) | **否** | sparkline（`summary.py:307/330` 恒 list 长 12） |
| `trend_slope_pct_per_week` | number | 是 | sparkline 颜色（`summary.py:326` None when no sales） |
| `realized_profit_eur` | number | 是 | 盈亏 badge |
| `inventory_cost_value_eur` | number | 是 | 盈亏 badge |
| `last_purchase_days_ago` | number | 是 | fmtDays 列（`summary.py:354` None） |
| `last_purchase_at` | str(ISO) | 是 | ordered 自动清（`summary.py:353` None） |
| `restock_qty_p50` | number | 是 | 推荐列 / kpi spend（`restock_calc.py:334`） |
| `restock_qty_p98` | number | 是 | p98 文本列（`restock_calc.py:335`） |
| `restock_source` | str | 是 | 推荐列 title（`restock_calc.py:336`） |
| `last_purchase_qty` | number | 是 | 上次进货量列（`restock_calc.py:337`） |
| `urgency_score` | number | 是 | urgencyCell / filter band / sort / kpi / 概览（可 None） |
| `stockout_zero_weeks_last8` | number | **否** | 缺货 badge（`restock_calc.py:340` `fc[3] if fc else 0`，恒 int） |

> `restock_qty_p50/p98/source/last_purchase_qty` 标可空属保守（旧 JS 以 `!= null` 处理）；实现期若确认 service 恒非空，收紧为非空并补证据。**非空标记一旦定，strict schema 必填，service 漏值即 500 暴露**（正是要的行为）。

**不进 RestockItem（drawer/urgencyTip 专属，Phase 2 再扩 schema）**：`urgency_breakdown`、`total_qty`、`n_active_weeks_26w`、`retail_price_observed/estimate`、`retail_qty_26w`、`retail_revenue_26w`、`retail_share_26w`、`inventory_sale_value_eur`、`lifetime_invested_eur`、`lifetime_purchase_qty`、`lifetime_sale_qty`、`lifetime_sale_revenue_eur`、`net_cashflow_eur`、`inventory_imbalance_pct`、`is_history_truncated`、`first_event_at`。

测试：`RestockItem` schema 喂**满字段非空**的真 payload（含 list[number] 长 12），验 `extra="forbid"` 不漏不拒。

改后跑 `cd frontend` 外的 `python tools/gen_ts_types.py`（CI `--check`）→ types.gen 出 `RestockItem`，前端直接 import。

---

## 4. 死代码 / 不迁项证据（保留）

| 项 | 证据 | 处理 |
|---|---|---|
| `GET /restock/decisions/{recent,stats,stale}` | 全仓 grep 无前端调用；2026-06-08 spec「前端零调用」 | 不迁，后端保留 |
| `POST /restock/decisions`（单条） | restock.js 只调 `/batch`(746)、`/suppressed`(1155) | 不迁，后端保留 |

均后端端点无前端 UI，不删代码。

---

## 5. 目标架构（对齐 `pages/history/`）

```
frontend/src/pages/restock/
├── RestockPage.vue       # 取数 + 状态（27k 行 shallowRef，§8）+ 组合
├── types.ts              # 视图模型；后端字段 import api/types.gen 的 RestockItem
├── normalize.ts (+test)  # RestockItemList → 视图行（仅展示派生）
├── filter.ts (+test)     # filterPredicate 1:1（纯函数，支持 skipSupplier）
├── sort.ts (+test)       # applySort（见 §6 审计偏离）
├── kpi.ts (+test)        # 紧急/关注/充足/补货额（无已标记）
├── supplier-summary.ts (+test)  # 见 §6 概览契约
├── cells.ts (+test)      # urgency(无tooltip)/cover/margin/fmtDays/fmt 等
├── suppressed-normalize.ts (+test)
├── ordered-store.ts (+test)
└── FilterBar/SupplierOverview/KpiCards/RestockTable .vue
```

router.ts 加 `{ path:"restock", name:"restock", component:()=>import("./pages/restock/RestockPage.vue") }`。

**样式（第1轮阻断#2）**：`.rs-*` 在 `static/css/components.css`，Vue 不加载它。**只把 Phase 1 渲染到的 `.rs-*` 规则移进组件 scoped `<style>`、用 token**；**不全局导入 legacy components.css**。吃 `frontend/index.html` 的 `data-theme` 引导，不复制 tokens.css。

---

## 6. 待移植纯函数 + 契约

| 纯函数 | 旧位置 | 必锁契约 |
|---|---|---|
| `filterPredicate(it, {skipSupplier})` | :285 | ordered→suppressed(除 skipped band)→origin→supplier→search(4字段)→views→band(70/40)→coverMax(仅active)。**band 用 `urgency_score ?? -1`**（见下 null 口径） |
| `applySort` | :340 | 见下「审计偏离」 |
| `computeKpi` | :1113 | pool 排除 disc/new/ordered/suppressed；hot≥70 / watch[40,70) / ok[0,40)；spend=Σ可见行 p50×(last_purchase_unit_price ?? master_stock_price_eur)。无已标记 |
| `supplierSummary`/`allSuppliersSummary` | :818/:834 | 见下「概览契约」 |
| `coverTone` | :189 | crit<0.5T/low<T/ok<2T/high≥2T；COVER_CAP=13.0 |
| `urgencyCell`(无tooltip)/`weeksOfCoverCell`/`marginCell` | :143/:176/:227 | high≥70/mid≥40；woc crit≤2/warn≤4/cold≥20；margin great≥50/good≥30/meh≥10/bad + `~` |
| `fmtDays`/`fmt` | :93/:101 | 今天/<30天/<365月/年；千分位 |
| `loadOrdered`/`autoClearOrderedByPurchase` | :54/:76 | 30 天 cutoff；`last_purchase_at>marked_at` 清 |

### 供应商概览契约（第2轮阻断#2，红队 FOREIGN/CN 案例）
旧 `_supplierSummary`/`_allSuppliersSummary` 吃 **`filterPredicate({skipSupplier:true})` 的池**——即「应用当前全部筛选，但忽略 supplier 筛选」（[restock.js:820](static/js/restock.js)）。**必须复用 filterPredicate 的 skipSupplier 分支**，不可吃全量 `items`。否则 filter=FOREIGN 时 CN 高分供应商会漏出，违反 1:1。
- 折叠态：`hot_count>0` 过滤，按 `hot_count desc`，top5
- 展开态：全量（过滤 supplier_id≠null & urgency_score≠null），按 `max desc`
- **必加组合测试**：concept = 当前 origin=FOREIGN/search/band/coverMax 各组合下，概览结果 = 同筛选忽略 supplier 后的聚合（含红队：FOREIGN 筛选时 CN 供应商**不得**出现）。

### null 紧迫分口径：band 过滤 ≠ KPI 计数（第3轮建议）
**两套口径不同，须分别照搬，不可统一**：
- `filterPredicate` band 用 `score = urgency_score ?? -1`：`band=ok` 判 `score >= 40 → 剔`，故 **null 行（−1 < 40）被保留**在「充足」筛选里。
- `computeKpi` 「充足(ok)」计 `s >= 0 && s < 40`：**null 行（−1 < 0）被排除**出计数。
- 即：band=ok 列表**含** null 紧迫分行，但 KPI「充足」数字**不含**。移植两函数各自锁测试，禁止顺手对齐。

### 审计偏离：applySort 两边 null（第2轮建议）
旧 comparator `av null→return 1` 无视 b：两边均 null 时返 1，违反反对称性（compare(a,b)=compare(b,a)=1）。**Phase 1 显式修正为两边 null→return 0**，作已审计 bug 修复，注释标注 + 单测锁新行为。这是对旧行为的**有意偏离**（仅影响两 null 行的稳定相对序），列此供用户批准时确认；其余排序行为严格 1:1。

### 常量真源（集中一处）
- 初始默认：`origin="FOREIGN"`、`views={active:true,new:false,disc:false}`、`band="all"`、`coverMax=4`、`coverThreshold=4`、`sort={urgency_score,desc}`、可见上限 500。
- **重置 ≠ 初始默认**：`origin=""`、`views={active:true,...}`、`band="all"`、`coverMax=null`、`supplier=null`、`search=""`。两套分别锁测试。
- 阈值：`HOT_URGENCY=70`、`OVERSTOCK_WEEKS=20`、`COVER_CAP=13.0`、`SUPPLIER_OVERVIEW_HOT=70`、`SUPPLIER_OVERVIEW_TOP=5`、`ORDERED_EXPIRY_DAYS=30`。
- 不迁：`SKIP_SUPPRESS_DAYS=14`（前端不用）。

---

## 7. 取数（只读）

| 源 | 用途 | 失败 |
|---|---|---|
| `GET /api/restock/items` | 主列表 | 表体显错误 |
| `GET /api/restock/suppressed` | 隐藏集 | 兜底 `{}` 不阻断 |
| `localStorage restock_ordered_v1` | 隐藏集 + 自动清 | try/catch `{}` |

`/api/*` 未登录 JSON 401 → 中性占位（非业务空态，`project_frontend_decoupling` 教训）。

---

## 8. 性能与导航

- **大列表响应式**：27k 行 `shallowRef` + `markRaw` 持原始数组，避免深层代理；筛选/排序产新数组替换引用。
- **导航**：侧栏「补货」**暂指旧页**；`/ui/restock` 作预览直达。Phase 3 写操作迁完再切主入口。

---

## 9. 验收（可执行）

### 后端
- `pytest tests/`：`RestockItem` 喂**满字段非空**真 payload（list_sku_summary 投影后）验 `extra="forbid"` 不漏不拒；`/api/restock/suppressed` 形状（含空 `{}`）。
- **投影 key 集断言（第3轮建议）**：`/api/restock/items` 投影后单行 `keys() == 白名单集`（多一个/少一个即挂），杜绝胖字段回流或漏投影。
- **非空字段拒 null（第3轮建议）**：对标非空的字段（origin/weekly_velocity/weekly_revenue/weekly_qty_12w/stockout_zero_weeks_last8/bool 们）各传一次 `None` → strict schema **拒绝**（验上游漏值会 500 暴露而非静默）；可空字段传 None → **通过**。
- **origin 枚举拒绝（第4轮阻断）**：`origin` 传枚举外值（如 `"HZ"`、`"XX"`）→ `Literal["FOREIGN","CN","unknown"]` **拒绝**。防上游错误值静默落入「前端无筛选入口」的行为不明态。
- `python tools/gen_ts_types.py --check` 退出 0。
- **性能门槛（可执行）**：同一固定 27k 行数据集，本地同机，预热 3 次、计时 10 次取 p50；`/api/restock/items` p50 ≤ `/analytics/list` p50 × **1.3**（投影减体积、校验增成本，净额受控）。脚本记录两端 p50 入 PR。

### 前端
- `cd frontend && npm test`（Vitest）覆盖 §6 每纯函数成功 + 边界，含：
  - resetFilters 两套值；filterPredicate 各 band/origin/coverMax/已跳过 组合
  - **供应商概览组合**（红队 FOREIGN→CN 不漏出）
  - applySort 审计偏离（两边 null→0）+ null 沉底
  - **band=ok 对 null 紧迫分**：列表保留 null 行 / KPI「充足」排除 null（两口径分别断言，§6）
  - **供应商点击清 coverMax**：概览 chip 与表格 supplier 按钮两入口，点击后 `supplier=X` 且 `coverMax=null`；红队断言 `weeks_of_cover=8` 行在点击后仍可见
  - suppressed **请求失败 + 空响应**；localStorage **损坏 + 过期边界**；货到自动清
  - 500 行渲染上限；401 中性状态
- **新旧一致**：同 items 固件喂新 `filter+sort`，barcode 序列 = 旧 `filterPredicate+applySort` 移植参照（除审计偏离点）。
- **前端性能门槛（可执行）**：27k 固件，`performance.now()` 预热 3 次、采样 20 次取中位；新 `filter+sort` 纯计算中位 ≤ 旧移植参照中位 × **1.5**（相对阈值，免机器依赖）。
- `cd frontend && npm run build`（vue-tsc）通过。
- **禁旧端点 guard**：照 history `no-analytics.test.ts` 先例，为 restock 页加同款断言——源码不含 `/analytics/`、`/restock/decisions`，只走 `/api/restock/*`。

### e2e（第1轮阻断#4）
- restock smoke **自建最小数据夹具**（独立 seed 几条 SKU，不依赖 Dashboard 导入 / 测试顺序），断言 `/ui/restock` 出行 + KPI 有数。纳入 smoke 子集。

### 视觉
- `./dev.ps1 -Frontend` 起栈，浏览器对照旧页：被渲染控件行集/KPI/概览一致（container-type:inline-size 塌陷须真浏览器验收）。

---

## 10. 不动清单

- `restock_calc.py`、`restock_decisions.py` 逻辑、所有 `/restock/decisions/*` 旧端点：零改动（restock.py 仅**新增** api_bp）。
- `/analytics/list`：零改动。
- 旧 `restock.js` + `_page_restock.html`：Phase 1 不删不改。

---

## 11. 证据措辞修正（第2轮建议）

`no-analytics.test.ts` 只对 history 页守护 `/analytics/sku`，**并非全局强制全栈走 `/api/*`**；它是**逐页 guard 先例/机制**。全栈契约由 §11 spec **文本**规定，靠**逐页 guard** 落地。Phase 1 据此为 restock 页加同款 guard（§9）。

---

## 12. 后续 Phase（备忘）

- **Phase 2**：drawer 只读（紧迫分四维/财务/盈亏，扩 schema 加回 `urgency_breakdown` 等）+ urgency tooltip + ⚑ 勾选 + 批量栏（不写库）。
- **Phase 3**：写操作（`POST /api/restock/decisions/batch`）+ 凑单 + 撤销 + CSV/boson 导出 + p98 可编辑 + knob，失败路径 & 红线测试。
- **Phase 4**：侧栏主入口切 `/ui/restock` + 退役旧页 + 旧 hash 入口 302 + e2e smoke。
