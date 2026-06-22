# 补货决策页 Vue 迁移 — Phase 2（只读 drawer 明细）设计

> **Status:** 设计待批（brainstorm 完成，待用户审 spec）
> **前序:** Phase 1（只读列表 + 筛选 + 排序 + KPI + 供应商概览）已上线 = main `e9324a0`（PR #86）。
> **Spec:** `docs/superpowers/specs/2026-06-20-restock-vue-phase1-design.md`（Phase 1，§12 已划本期范围）。

## 1. 目标与切割线

补货页 `/ui/restock` 命中行点击展开**只读 drawer 明细**（单 SKU 财务/库存/盈亏/销售概况/紧迫分四维），1:1 对齐旧 `renderDrawer` 的只读部分。**纯只读增量**——列表 / `items` 端点 / `RestockItem` 零改动，瘦投影不受影响。

### Phase 2 范围
- 点行**内联展开** drawer（旧页 `rs-drawer-row`，1:1），**同时只展开一行**
- drawer 5 段：财务快照 / 库存 / 累计盈亏 / **销售概况** / 紧迫分四维（四维拆解 + 分位）
- 新增唯一瘦端点 `GET /api/restock/<barcode>/detail`（懒加载，复用 `compute_restock_snapshot`）

### 明确省略（→ Phase 3）
- drawer **操作按钮**（标记已下单 / 抑制 / 撤销）= 写操作
- ⚑ 勾选 / 批量栏 / 导出 / p98 编辑 / 凑单 / cover knob
- **列表 urgency 单元格 hover tooltip**：四维拆解只在 drawer（用户决策），列表 urgency 列保持 Phase 1（bar + 数字），`RestockItem` 不加 `urgency_breakdown`

### 用户可见行为红线
> 本期渲染的 drawer 内容只读，严格按**准确口径**展示（见 §4 销售概况口径修正）；不照搬旧页误导性标签（口径错误 = 同 RL-1 文案性质，不传播）。

---

## 2. API 契约

**新增（`app/routes/restock.py` 的 `api_bp` 下，`app/routes/__init__.py` 已注册 `restock_api_bp`）：**

| 端点 | 服务 | 响应 |
|---|---|---|
| `GET /api/restock/<barcode>/detail` | `compute_restock_snapshot(barcode)`（**物化单行优先 `_read_sku_summary_row` ~1ms**，表空/过期回退 `list_sku_summary` filter）| `RestockDetailResponse { ok: true, detail: RestockDetail }` |

- **不碰** `/api/restock/items`（列表瘦投影冻结）、不碰旧 `/analytics/*`、不碰 `restock_calc.py`/`restock_decisions.py` 逻辑（仅新增路由）
- `compute_restock_snapshot` 返回 `None`（barcode 不在汇总：停用 / 无主档 / 未知）→ 端点 **404**（`jsonify({"ok": False, "error": "not_found"}), 404`）
- 投影 **必须显式处理嵌套**（真实 `urgency_breakdown` dict 有 8 键含 `margin_missing`，**整 dict 透传会被 `extra="forbid"` 拒 → 500**，正是 history Phase 2b 事故）：
  ```python
  _BD_KEYS = tuple(RestockDetailUrgencyBreakdown.model_fields)            # 7 键（不含 margin_missing）
  _DETAIL_FLAT_KEYS = tuple(k for k in RestockDetail.model_fields if k != "urgency_breakdown")
  def _project_detail(row: dict) -> dict:
      out = {k: row.get(k) for k in _DETAIL_FLAT_KEYS}
      bd = row.get("urgency_breakdown")
      out["urgency_breakdown"] = {k: bd.get(k) for k in _BD_KEYS} if bd else None  # 逐字段，丢 margin_missing
      return out
  ```
- strict `extra="forbid"`；**投影 key 集 + 嵌套 key 集后端测试均钉死**（多/少即挂，杜绝胖字段回流 + margin_missing 回潮）

### RestockDetail 字段白名单（扁平 + 一个嵌套）

| 组 | 字段（nullability 以 `compute_restock_snapshot` 真实输出为准，测试喂满 + 喂 null 各锁一遍）|
|---|---|
| 标识 | `barcode:str` |
| 财务快照 | `master_sale_price_eur`、`sale_net_avg`、`retail_price_observed`、`retail_price_estimate`、`last_purchase_unit_price`、`master_stock_price_eur`、`margin_source`、`margin_pct`（均 `\|None`）|
| 库存 | `qty_total:int\|None`、`inventory_sale_value_eur\|None`、`inventory_cost_value_eur\|None`、`weeks_of_cover:float\|None` |
| 累计盈亏 | `realized_profit_eur\|None`、`lifetime_invested_eur\|None`、`lifetime_purchase_qty\|None`、`lifetime_sale_revenue_eur\|None`、`lifetime_sale_qty\|None`、`net_cashflow_eur\|None`、`inventory_imbalance_pct\|None`、`is_history_truncated:bool`、`first_event_at:str\|None` |
| **销售概况**（§4 口径）| `total_qty:int\|None`（**累计批发量**）、`n_active_weeks_26w:int`、`weekly_velocity:float`、`weekly_revenue:float`、`retail_qty_26w:int`、`retail_revenue_26w:float`、`retail_share_26w:float` |
| 紧迫分 | `urgency_score:float\|None`、`urgency_breakdown: RestockDetailUrgencyBreakdown \| None` |

### RestockDetailUrgencyBreakdown（**独立新模型，不复用 History 的 5 字段 `UrgencyBreakdown`**）

`extra="forbid"`，嵌套**逐字段显式投影**（不整 dict 透传 — `feedback_strict_schema_nested_projection`，history Phase 2b urgency_breakdown 整体透传致 500 的事故）：

```
velocity: float        # 销额维得分 /30
cover: float           # 库存维得分 /30
recency: float         # 距进货维得分 /10
margin: float          # 毛利维得分 /30
demand_validity: float | None   # 长尾活跃度折扣
velocity_pctile: float | None   # 销额分位（drawer 销额行内显示）
margin_pctile: float | None     # 毛利分位（drawer 毛利行内显示）
```

> History 的 `UrgencyBreakdown` 只有 `{cover, recency, velocity, margin, demand_validity}`、**无 pctile**；扩它会耦合两消费方 + 撞 History strict。故独立。

### gen_ts_types
`python tools/gen_ts_types.py` 同步 `RestockDetail` / `RestockDetailUrgencyBreakdown` / `RestockDetailResponse`；CI `--check` 守护。

---

## 3. 前端架构

### 组件
- **`RestockDrawer.vue`** — props `{ barcode }`，自取数渲染 5 段；移植 `renderDrawer` 只读部分（去操作按钮）。展示纯函数 `drawer-cells.ts`（盈亏状态档 / 零售价行 / 净现金流行 / 销售概况标签 / 四维 scoreBreakdown 几何）+ 各自 Vitest。
- **`stores/restockDetail.ts`（keyed Pinia store）** — 按 barcode 分区，多 SKU 缓存 + 并发隔离（见 §5）。
- **`RestockTable.vue`** — 行加 clickable（cursor + `tabindex=0` + `aria-expanded` + Enter/Space）；点击 emit `toggle-expand(barcode)`。命中 `expandedBarcode` 时该行后插 `<tr class="rs-drawer-row"><td colspan="14"><RestockDrawer :barcode/></td></tr>`。**行内交互元素 `rs-bc-link`/`rs-supplier` 加 `@click.stop`**（防冒泡误展开，§5 红队）。
- **`RestockPage.vue`** — `expandedBarcode: shallowRef<string|null>`，`onToggleExpand(bc)`（同 bc 收起 / 异 bc 切换），传 RestockTable。

### 数据流
1. 点行（非货号/供应商按钮）→ `expandedBarcode = bc`（同 bc → `null` 收起）
2. RestockTable 插 drawer 行（`:key="bc"`）→ `RestockDrawer` `onMounted/watch(barcode)` 调 `store.load(bc)`
3. store：`cache[bc]` 命中 → 立即 `ready`；否则 `inflight[bc]` 合并 → `apiGet` → 写 `cache[bc]` + `entries[bc]=ready`
4. drawer 按 `entries[bc]` 状态渲染：`loading` 占位 / `ready` 5 段 / `missing` 「无补货明细」/ `error` 「明细加载失败，点重试」

---

## 4. 销售概况口径修正（必须，防误导）

旧 drawer「📊 销售(26 周): 批发 `total_qty` 件 / €`weekly_revenue×26`」**双重错标**：
- `total_qty`（`summary.py:300` = `sum(qty for wholesale_sales)`）= **累计终身批发量**，非 26 周（真实 26 周批发量是 `recent_qty`，未入 payload）
- `weekly_revenue × 26` = 周均额外推，**非真实 26 周批发额**（真实是 `recent_revenue`，未入 payload）

**口径决定（Phase 2 不新增汇总字段，只准确标注已有字段）：** 段标题改「**销售概况**」，展示：
- 累计批发量 `total_qty`（明标"累计"，不冠 26 周）
- 近 26 周活跃周 `n_active_weeks_26w`
- 周销速 `weekly_velocity` 件/周 · 周销额 `weekly_revenue` €/周（明标 per-week，**不 ×26 外推**）
- 真实零售 26 周 `retail_qty_26w` 件 / €`retail_revenue_26w`（这两个本就是真实 26 周窗口）+ 零售占比 `retail_share_26w`

> 不展示"26 周批发总量/总额"——真实值未在 payload，外推值误导。需要时 Phase 3 另议是否把 `recent_qty/recent_revenue` 入 payload。

---

## 5. keyed store + 并发/错误契约

`stores/restockDetail.ts`（Pinia，按 barcode 分区）：

```
state:
  entries: Record<bc, "loading" | "ready" | "missing" | "error">
  cache:   Record<bc, RestockDetail>     // 仅成功结果
  inflight: Record<bc, Promise>          // 合并同 SKU 并发
  errorMsg: Record<bc, string>

load(bc):
  if cache[bc] → entries[bc]="ready"; return
  if inflight[bc] → await 它（合并）
  entries[bc]="loading"
  try: detail = (await apiGet(`/api/restock/${bc}/detail`)).detail
       cache[bc]=detail; entries[bc]="ready"
  catch e:
    if e instanceof UnauthenticatedError → return（401 中性，不写业务错；apiGet 已跳登录）
    else if e instanceof ApiError && e.status===404 → entries[bc]="missing"
    else → entries[bc]="error"; errorMsg[bc]=e.message   // 500/网络：不写 cache，重开可重试
  finally: delete inflight[bc]
```

**为何 keyed 优于 single-vm + request-id**：A/B 响应各只写自己 key，**A 迟到只填 `cache[A]`，绝不污染当前展示的 B drawer**（不同 key 天然隔离）；多 barcode 缓存白送（重开任意已载 SKU 秒开）；`inflight` 合并快速重复展开同 SKU。

### `ApiError`（client.ts，向后兼容）
```ts
export class ApiError extends Error { constructor(public status: number, msg: string){ super(msg); } }
// apiGet 的 !res.ok 分支：throw new ApiError(res.status, `API ${res.status}: ${path}`)
```
仍 `extends Error`，既有 `catch (e) { (e as Error).message }` 不破；store 可 `e instanceof ApiError && e.status===404`。

### 红队（行点击冒泡）
- 点**货号** `rs-bc-link` → 仅 `open-history`，**不展开 drawer**（`@click.stop`）
- 点**供应商** `rs-supplier` → 仅 `select-supplier`，**不展开 drawer**（`@click.stop`）
- 点行其余区域 → 展开/收起 drawer
- 键盘 focus 行 Enter/Space → 展开/收起；`aria-expanded` 反映态

---

## 6. 测试（可执行）

### 后端
- `RestockDetail` strict：满字段真 payload（`compute_restock_snapshot` 输出形状）`extra="forbid"` 不漏不拒；各 nullable 字段喂 `None` 通过、非空字段喂 `None` 拒；额外键拒
- `RestockDetailUrgencyBreakdown`：嵌套满字段 + pctile=None 通过 + 额外键拒（防整 dict 透传回潮）
- 投影 key 集：`_project_detail` 喂超集（含 drawer 外胖字段 + `urgency_breakdown` 含 `margin_missing`）→ 顶层 `keys()==RestockDetail 字段集` **且** `out["urgency_breakdown"].keys()==_BD_KEYS`（**显式断言 `margin_missing` 被丢弃**）
- `/detail` 端点：seed 物化 `SkuSummary` → 200 `{ok:true, detail:{...}}`；未知 barcode → 404 `{ok:false}`
- **结构性（非毫秒）**：mock `compute_restock_snapshot`，断言 `/detail` **只调它一次** + 返回投影后 key 集（机器/缓存态无关，不 flaky）。**perf 仅人工 bench 记 PR，不入 CI 断言**

### 前端
- `drawer-cells.ts` 纯函数：盈亏四档（已回本/压货中/账面亏损/缺成本）、零售价 observed/estimate 分支、净现金流 imbalance 警告、**销售概况标签准确**（累计批发 vs 周销额 per-week 不混淆 + 不出现"×26")
- `RestockDrawer.vue`：渲染 5 段 + **无操作按钮**；`missing/error/loading` 三态占位；销售概况无外推文案
- `restockDetail` store：`cache` 命中不重拉；`inflight` 合并同 SKU；**A/B 隔离**（载 A 未完切 B，A 迟到只填 cache[A] 不动 B drawer）；404→missing；500→error 不缓存可重试；401→中性不写错
- `RestockTable`：点行展开/收起（单行 / colspan=14 / drawer 行现）；**红队：点货号/供应商不展开**（`@click.stop`）；Enter/Space 展开 + `aria-expanded`
- `client.ts`：`ApiError` 带 status + `instanceof Error` 仍真
- **no-analytics guard 仍过**：drawer 只走 `/api/restock/*`

### e2e
- restock smoke 扩：seed 夹具 → 点行 → `tr.rs-drawer-row` 现 + 5 段标题在

### gen_ts_types
- `python tools/gen_ts_types.py --check` 退出 0

---

## 7. 不动清单
- `restock_calc.py`（`compute_restock_snapshot` 仅**调用**不改）、`restock_decisions.py`、`/restock/decisions/*`、`/analytics/*`、旧 `restock.js`/`_page_restock.html`：零改动
- `/api/restock/items` + `RestockItem`：冻结
- 侧栏「补货」仍 `legacyPageId`（主入口 Phase 4 才切）

## 8. 后续 Phase（备忘）
- **Phase 3**：写操作（`POST /api/restock/decisions/batch` + 凑单 + 撤销 + CSV/boson 导出 + p98 编辑 + cover knob）+ ⚑勾选/批量栏 + drawer 操作按钮 + 红线测试
- **Phase 4**：侧栏主入口切 `/ui/restock` + 退役旧页 + 旧 hash 302 + e2e
