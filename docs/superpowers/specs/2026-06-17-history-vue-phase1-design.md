# 货号历史页迁移 Vue —— Phase 1（核心查询 + 变更溯源）设计

**状态：** 已批准（边界 + 5 条硬约束，2026-06-17）

## 目标

把「货号历史」页的**查询核心**（搜索 → 当前状态 → 历史事件线）迁移到 Vue 独立栈 `/ui/history`，作为该重页 4 阶段迁移的第一阶段。**Phase 1 是 additive 迁移**：不退役旧页、不接分析/SVG/批次。

## 范围

### 做（Phase 1）
- 搜索框（条码/型号）+ Enter 触发 + RECENT chips
- 模糊候选表（精确未中时）+ 行点击切换目标
- 命中：hero（型号/条码/状态/grade/复制）+ 概况（品名×2/位置/售价/来源/更新）+ 历史时间线（events 倒序）
- 数据源：**仅** `GET /api/history?q=<查询>`（复用 `history_service.build_response`）
- 入口策略 C：nav 翻 routeName；新页顶部「查看完整分析（旧版）→」深链 `/?page=history`

### 不做（Phase 2+，硬约束 #2）
- 销售分析 / 采购面 / 深度 extras / 补货决策快照（`GET /analytics/sku/<barcode>`）→ Phase 2
- 销售/进价 SVG 时间线（`.../timeline`）→ Phase 3
- 批次记录 tab（最近改动 recent-changes + 扫描批次 scan-history）→ Phase 4

---

## 硬约束（写死，coder 不得自行发挥）

**HC-1（additive，不退役）：** Phase 1 **不得**退役旧货号历史页。`static/js/store.js` 的 `{ id: "history", ... }`、`templates/partials/_page_history.html`、`static/js/history.js` **全部保留不删**。主导航可切到新页，但**必须**保留「查看完整分析（旧版）」明确入口（深链 `/?page=history`）。

**HC-2（不接分析/SVG/批次）：** Phase 1 代码**不得**调用或引用 `/analytics/sku/`、`/timeline`、recent-changes、scan-history。不得为"顺手"接半截分析。

**HC-3（文案不暗示全量完成）：** 页面副标题/文案标明这是"核心查询 / 变更溯源"版本，完整分析见旧版。不得出现"完整/全量货号历史"等暗示 parity 的文案。

**HC-4（七状态全覆盖）：** 搜索 UX 必须实现并测试 7 个状态：初始 / loading / 无结果（精确未中且无候选）/ 多候选（fuzzy）/ 精确命中 / 请求失败 / 命中但事件为空。

**HC-5（normalize 单点收窄）：** 数据边界只在 `frontend/src/pages/history/normalize.ts` 一处收窄。组件只消费 VM，**不得**直接读 raw `/api/history` payload。

**HC-6（schema 逐字段对齐真实 build_response）：** `HistoryCurrent` 必须含 build_response 当前真实全部字段（下方 schema 已逐字段核对 `app/services/history.py` + `app/models.py`），**不得**只写页面用到的字段——否则 `extra="forbid"` 会把合法 payload 打成 500。

**HC-7（pydantic 只约束 200）：** `/api/history` 的错误响应（空 q 的 400、未登录 401）**不走** `HistorySearchData`：空 q → `{ok: false, msg}` 400；未登录 → 全局 auth 的 `{error: "unauthenticated"}` 401。pydantic 校验只作用于 200 成功响应。

---

## 后端

### 端点
`app/routes/history.py` 现有 `bp`（`/history`，旧 SPA 在用，**保留**）。**新增** `api_bp`（`/api/history`）：

```python
api_bp = Blueprint("api_history", __name__, url_prefix="/api/history")

@api_bp.get("")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"ok": False, "msg": "缺少查询参数"}), 400   # HC-7：不走 schema
    from app.schemas_api import HistorySearchData
    result = history_service.build_response(q)   # {found, current?, events?, fuzzy_matches?}
    return jsonify(HistorySearchData.model_validate({"ok": True, **result}).model_dump())
```
在 `app/routes/__init__.py` import `api_bp as history_api_bp` 并 `register_blueprint`（保持 isort 顺序）。

> 异常策略对齐 `/api/briefing/data`：系统级异常（DB/schema）不在端点吞，让其冒泡到 Flask 通用 500（不把 SQL 文案泄给客户端）。

### pydantic schema（`app/schemas_api.py`，已逐字段核对 service + models —— HC-6）

来源核对：`find_record`（current 15 字段）+ build_response 追加 `store/warehouse/unknown_locations` + `aggregate_full_timeline`（events）+ `find_fuzzy_matches`（候选）。类型来自 `app/models.py`：`Stockpile.{product_model:str, stockpile_location:str, manual_grade:int|None, stock_price/sale_price:float|None, is_truly_discontinued:bool, source/created_at/updated_at/product_name_*/erp_category_*:str|None}`；`is_active` 经 `bool(...)` 转布尔；`InventoryEvent.event_at:str(Text)`、`StockpileChange.{field_name:str, old_value/new_value/change_type:str|None, created_at:str(Text)}`。**所有时间戳均为 Text 字符串，无 date/datetime 对象**（pydantic `str` 安全）。

```python
class HistoryLocSplit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stores: list[str]
    warehouses: list[str]
    unknown: list[str]

class HistoryChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    old: str | None
    new: str | None
    old_split: HistoryLocSplit | None = None   # 仅 field == stockpile_location 时出现
    new_split: HistoryLocSplit | None = None

class HistoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    at: str
    change_type: str | None        # HC-2 注：build_response 后 source 可能仍为 None（record.source 本身 str|None）
    source: str | None
    summary: str | None = None     # 仅 inventory_events 事件有；stockpile changes 走 changes[]
    changes: list[HistoryChange]   # inventory_events 为 []

class HistoryCurrent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    barcode: str
    model: str
    location: str
    is_active: bool
    source: str | None
    created_at: str | None
    updated_at: str | None
    product_name_zh: str | None
    product_name_local: str | None
    erp_category_raw: str | None
    erp_category_code: str | None
    manual_grade: int | None
    stock_price: float | None
    sale_price: float | None
    is_truly_discontinued: bool
    store_locations: list[str]
    warehouse_locations: list[str]
    unknown_locations: list[str]

class HistoryFuzzyMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    barcode: str
    model: str
    location: str | None
    is_active: bool

class HistorySearchData(BaseModel):
    """GET /api/history?q= 的 200 响应。三种分支：
    命中 {found:true, current, events}；模糊 {found:false, fuzzy_matches}；无 {found:false}。
    缺省分支字段用 Optional 兜（build_response 按分支省略 key）。"""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    found: bool
    current: HistoryCurrent | None = None
    events: list[HistoryEvent] | None = None
    fuzzy_matches: list[HistoryFuzzyMatch] | None = None
```
`API_MODELS` 追加 `HistorySearchData`（嵌套模型经 `$defs` 自动进 types.gen.ts）。`python tools/gen_ts_types.py` 同步。

---

## 前端

### VM（`frontend/src/pages/history/types.ts`）—— discriminated union 表达七状态里的"结果形态"
```typescript
export interface LocSplitVM { stores: string[]; warehouses: string[]; unknown: string[]; }
export interface ChangeVM { field: string; old: string | null; new: string | null; oldSplit: LocSplitVM | null; newSplit: LocSplitVM | null; }
export interface EventVM { at: string; changeType: string | null; source: string | null; summary: string | null; changes: ChangeVM[]; }
export interface CurrentVM {
  barcode: string; model: string; isTrulyDiscontinued: boolean; manualGrade: number | null;
  productNameZh: string | null; productNameLocal: string | null;
  storeLocations: string[]; warehouseLocations: string[]; unknownLocations: string[];
  salePrice: number | null; source: string | null; updatedAt: string | null;
}
export interface FuzzyVM { barcode: string; model: string; location: string | null; isActive: boolean; }
export type HistoryResult =
  | { kind: "notfound" }
  | { kind: "fuzzy"; matches: FuzzyVM[] }
  | { kind: "hit"; current: CurrentVM; events: EventVM[] };
```
（"初始 / loading / 失败"是 store 的 `loading`/`error`/`result===null` 状态，不在 result union 里。）

### normalize（`frontend/src/pages/history/normalize.ts`，HC-5 单点收窄）
入 `HistorySearchData` → 出 `HistoryResult`：`found===false && fuzzy_matches?.length` → `fuzzy`；`found===false` → `notfound`；`found===true` → `hit`（current + events 全字段 camelCase 收窄，null/缺字段兜底）。组件只吃 `HistoryResult`。

### store（`frontend/src/stores/history.ts`，镜像 briefing/forecastEval）
`result: HistoryResult | null`、`loading`、`error`、`load(q: string)`。`load` 调 `apiGet<HistorySearchData>('/api/history?q=' + encodeURIComponent(q))` → normalize；`UnauthenticatedError` 吞（apiGet 已跳登录）；其它 error 填 `error`。**store/client 只允许 `/api/history`（HC-2 第一层防线）**。

### 页面（`frontend/src/pages/history/HistoryPage.vue`）
- `PageHeader` title="货号历史" subtitle="核心查询 / 变更溯源（完整分析见旧版）"（HC-3）
- 顶部安全阀：`<a href="/?page=history">查看完整分析（旧版）→</a>`（HC-1）
- 搜索区：input + 查询/重置 + Enter + RECENT chips（localStorage key `history.recentQueries`，与旧页连续）
- 七状态渲染（HC-4）：初始提示 / loading "查询中…" / notfound "未找到…" / fuzzy 候选表（行点击 → `load(barcode)`）/ hit（hero + 概况 + 时间线）/ error 错误态 / hit 但 events 空 → "暂无历史变更"
- 复制货号：**保留** navigator.clipboard + `execCommand` 兜底双路径（旧页的 HTTP 局域网兼容逻辑——内网非 secure context 下 `navigator.clipboard` 不可用，必须兜底）
- token 以 `static/css/tokens.css` 为单源，对照 BriefingPage.vue 用过的变量

### 路由 + nav
- `router.ts`：`children` 加 `{ path: "history", name: "history", component: () => import("./pages/history/HistoryPage.vue") }`
- `nav-items.ts`：`history` 由 `legacyPageId: "history"` → `routeName: "history"`；注释计数更新（已迁 3 项）

---

## 测试 / 验收

### 后端（`tests/test_history_api.py`）
- 未登录 → 401 `{error:"unauthenticated"}`（HC-7）
- 空 q → 400 `{ok:false}`（不走 schema，HC-7）
- 精确命中 → 200，`found:true`，current 全字段，events 有
- 模糊 → 200，`found:false`，fuzzy_matches 有
- 无结果 → 200，`found:false`，无 current/fuzzy
- seed 走 SQLAlchemy（参照既有 history/stockpile 测试 seed）

### 前端（vitest）
- `normalize.test.ts`：notfound / fuzzy / hit（含 location split change + inventory summary event + 空 events）三/四分支
- `history.test.ts`（store）：load 命中填 result、load 失败填 error、unauth 吞
- `HistoryPage.test.ts`：七状态各渲染断言 + fuzzy 行点击触发 load + 「完整分析（旧版）」链接存在且 href=`/?page=history`（mock store plain object 范式）
- `SidebarNav.test.ts`：history=RouterLink + 不再有 `/?page=history` 的 legacy nav `<a>`（注：与上面页面内 back-link 区分——back-link 在 HistoryPage 不在 SidebarNav）

### 机械守护测试（HC-1 + HC-2，用 Python，放 `tests/`）
- **HC-1 旧页保留**：断言 `static/js/store.js` 含 `{ id: "history"`、`templates/partials/_page_history.html` 存在、`static/js/history.js` 存在
- **HC-2 不接分析**：扫描 `frontend/src/pages/history/` 与 `frontend/src/stores/history.ts` 源码，断言**不含**字符串 `/analytics/sku` 和 `/timeline`（第二层防线；第一层是 store 只调 `/api/history`）

### 最低验收（用户定）
搜索命中渲染 hero+概况 ✓ / fuzzy 可点切换 ✓ / events 倒序 + 空态 ✓ / 不调 `/analytics/sku/*` 和 `/timeline` ✓ / 旧版完整页仍可访问 ✓ / 前端测试覆盖 normalize+store+页面状态 + nav/入口策略测试 ✓

---

## 不做（YAGNI）
分析块、SVG、批次 tab、概况里的"深度"子 tab、ERP 分类/进价展示（旧页概况本就不展示进价，沿用）。
