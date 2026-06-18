# 货号历史页迁移 Vue —— Phase 4a（批次记录 tab 壳 + 最近改动）设计

**状态：** 设计待批（2026-06-18）。

## 目标

给 `/ui/history` 加**一级 tab 壳**（货号查询 ↔ 批次记录），并迁移批次记录 tab 的**最近改动**子面板（recent_changes：按 import 批次看 stockpile 变更）。数据走**新建 strict `/api/` 双端点**。仍 **additive**：旧 SPA 货号历史页 / 旧 `/recent_changes/*` 端点 / 「查看完整分析（旧版）→」深链全保留。

货号历史 4 阶段已完成 P1/2a/2b/3（查询 tab 全部内容）。本期 = 批次记录 tab 的前半（4a＝最近改动）。**扫描批次 = 4b**；**Phase 4c** 统一退役旧页 + 旧 `/recent_changes/*` + 旧 `/scan_history/*` + 删「旧版」深链。

## 范围

### 做（Phase 4a）
- 货号历史页加一级 tab：**货号查询**（现 P1-3 内容）↔ **批次记录**。搜索框仅查询 tab 显示。批次 tab 首次激活 lazy 加载。
- 批次记录 tab 的**最近改动**子面板（1:1 复刻旧 `index-recent-changes.js`）：批次下拉（含「🔄 进行中开放批次」）→ 5 统计盒（可点筛选）+ roundtrip 备注 + 筛选 chips + collapsed↔raw 模式切换 + 变更列表（RENDER_CAP 300 + 「共 N」备注）+ 行点击下钻（切回查询 tab 跑该货号搜索）。
- 新建 strict `/api/history/recent-changes/{batches,<batch_id>/changes}` 双端点。

### 不做（YAGNI / 留后续）
- 扫描批次（scan_history）→ Phase 4b。
- 退役旧页 / 删旧 `/recent_changes/*` / 删「旧版」深链 → Phase 4c。
- 不动旧 SPA / 旧端点。

---

## 硬约束（写死）

**HC-4A-1（additive）：** 旧 SPA 货号历史页（store.js / `_page_history.html` / `history.js` / `index-recent-changes.js`）+ 旧 `/recent_changes/*` 端点 + 「旧版」深链全不动。

**HC-4A-2（strict 双端点，统一行形状）：**
- `GET /api/history/recent-changes/batches` → `{ok, batches: list[RecentChangeBatch]}`。
- `GET /api/history/recent-changes/<batch_id>/changes?mode=&field=&change_type=` → `{ok, summary: RecentChangeSummary, changes: list[ChangeRow]}`。summary 折进此端点（对齐 2 端点契约；summary 始终是该批次**全量**统计、与 filter 无关）。
- collapsed（from_value/to_value/latest_at）与 raw（old_value/new_value/created_at）由端点**统一投影**成单一 `ChangeRow`（barcode/model/field/from_value/to_value/change_type/at），strict schema + TS 干净。
- 只调 `recent_changes_service.{list_recent_imports, get_batch_summary, get_batch_changes}`；**不复用**旧 `/recent_changes/*` 路由。响应 key 集合后端测试断言。

**HC-4A-3（负 batch_id 支持）：** 开放批次 id = `-1`，Flask `<int:>` converter 不匹配负数 → 路由用 `<batch_id>`（str）+ 手动 `int()` 解析（含负数），非法 → 400（沿用旧 `_parse_batch_id` 语义）。

**HC-4A-4（mode/filter 校验）：** `mode ∈ {collapsed, raw}`（默认 collapsed），非法 → 400；`field` / `change_type` 可选透传给 service。

**HC-4A-5（失败隔离 + HC-B7）：** 批次记录 tab 用**独立 store** `useRecentChangesStore`，独立 loading/error。其失败不影响查询 tab（P1-3）。**per-batch 取数加 HC-B7 单调 request-id**（批次 A→B 快切，A 后到不得覆盖 B 的 summary/changes）；store reset 递增 seq。401 沿用 `apiGet` 全局语义（吞 `UnauthenticatedError` 不写块内 error）。

**HC-4A-6（tab 壳零重构）：** HistoryPage 加 tab 状态；**现有 P1-3 查询内容整体包进 `v-show="activeTab==='search'"`，不改其内部结构**（零风险）。批次 tab 容器 `v-if` lazy（首次激活才挂 `RecentChangesPanel`，避免无谓请求）。搜索框（含 RECENT chips）仅查询 tab 显示。

**HC-4A-7（下钻）：** 最近改动变更行点击 → 切 `activeTab='search'` + 调现有 `runSearch(barcode)`（复用查询 tab 逻辑，不另写搜索）。

**HC-4A-8（渲染上限）：** 变更列表前端渲染 cap 300 行 + 「仅显示前 300 / 共 N 条」备注（沿用旧 RENDER_CAP；端点返回全量，前端 cap DOM）。

**HC-4A-9（守卫延续）：** `no-analytics.test.ts` 扫描集**纳入** `stores/recentChanges.ts`（连同已纳入的 4 个 sku* store）；FORBIDDEN 仍 `["/analytics/sku"]`（新端点 `/api/history/recent-changes/*` 不含该子串 → 通过）。

---

## 后端

### 端点（`app/routes/history.py` 的 `api_bp`）
```python
_RC_VALID_MODES = ("collapsed", "raw")


@api_bp.get("/recent-changes/batches")
def recent_changes_batches():
    from app.schemas_api import RecentChangesBatchList
    from app.services import recent_changes as rc

    payload = {"ok": True, "batches": rc.list_recent_imports()}
    return jsonify(RecentChangesBatchList.model_validate(payload).model_dump())


@api_bp.get("/recent-changes/<batch_id>/changes")
def recent_changes_detail(batch_id: str):
    from flask import request

    from app.schemas_api import RecentChangesDetail
    from app.services import recent_changes as rc

    try:
        bid = int(batch_id)                       # HC-4A-3 含负数（-1 开放批次）
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad_batch_id"}), 400
    mode = request.args.get("mode", "collapsed")
    if mode not in _RC_VALID_MODES:               # HC-4A-4
        return jsonify({"ok": False, "error": "bad_mode"}), 400
    field = request.args.get("field") or None
    change_type = request.args.get("change_type") or None

    summary = rc.get_batch_summary(bid)
    raw_rows = rc.get_batch_changes(bid, mode=mode, filter_field=field, filter_change_type=change_type)
    changes = [_project_change_row(r, mode) for r in raw_rows]   # 统一行形状
    payload = {"ok": True, "summary": summary, "changes": changes}
    return jsonify(RecentChangesDetail.model_validate(payload).model_dump())


def _project_change_row(r: dict, mode: str) -> dict:
    """HC-4A-2：collapsed / raw 投影成统一 ChangeRow。"""
    if mode == "raw":
        return {
            "barcode": r["barcode"], "model": r["model"], "field": r["field"],
            "from_value": r["old_value"], "to_value": r["new_value"],
            "change_type": r["change_type"], "at": r["created_at"],
        }
    return {
        "barcode": r["barcode"], "model": r["model"], "field": r["field"],
        "from_value": r["from_value"], "to_value": r["to_value"],
        "change_type": r["change_type"], "at": r["latest_at"],
    }
```
- 路由前缀 `/api/history`（P1 蓝图）→ `/api/history/recent-changes/...`（不与 `<barcode>/...` 冲突：`recent-changes` 是静态段，Flask 路由静态段优先于 `<barcode>` 动态段；coder 实测确认 `/recent-changes/batches` 不被 `<barcode>/timeline` 等吞掉，若冲突则调整路由顺序/前缀）。
- 异常冒泡 500（与 timeline/extras 一致）。`/api/*` 未登录 → 全局 JSON 401。

### pydantic schema（`app/schemas_api.py`，逐字段对齐 recent_changes.py）
```python
class RecentChangeBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: int
    taken_at: str | None
    total_local: int | None
    change_count: int
    affected_barcodes: int
    is_open: bool

class RecentChangesBatchList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    batches: list[RecentChangeBatch]

class RecentChangeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location_changes: int
    model_changes: int
    inserts: int
    deactivates: int
    reactivates: int
    roundtrip_count: int

class ChangeRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    barcode: str
    model: str
    field: str
    from_value: str | None
    to_value: str | None
    change_type: str
    at: str

class RecentChangesDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    summary: RecentChangeSummary
    changes: list[ChangeRow]
```
`API_MODELS` 追加 `RecentChangesBatchList` + `RecentChangesDetail`，`gen_ts_types` 同步。

> 类型核对：`list_recent_imports` 行（recent_changes.py:90-134）；`get_batch_summary`（:263-289 6 int）；`get_batch_changes` collapsed（:242-252）/raw（:217-227）。`taken_at`/`total_local` 开放批次为 None → `| None`。`model` service 已 `models.get(bc,"")` 兜空串 → str 非空。`from_value/to_value/old_value/new_value` 可为 None → `| None`。

---

## 前端

### VM + normalize（`frontend/src/pages/history/recent-changes-{types,normalize}.ts`）
VM camelCase：`RecentBatchVM`(batchId/takenAt/totalLocal/changeCount/affectedBarcodes/isOpen)、`RecentSummaryVM`(locationChanges/modelChanges/inserts/deactivates/reactivates/roundtripCount)、`ChangeRowVM`(barcode/model/field/fromValue/toValue/changeType/at)。normalize 两个：`normalizeBatches`、`normalizeDetail`（snake→camel，null 透传）。

### store（`frontend/src/stores/recentChanges.ts`，HC-4A-5）
独立 pinia store：
- state：`batches`、`selectedBatchId`、`summary`、`changes`、`mode`('collapsed')、`filter`({field,changeType})、`loading`/`error`（batches 级）、`detailLoading`/`detailError`（per-batch 级）、闭包 `let seq=0`。
- `loadBatches()`：拉 `/api/history/recent-changes/batches`，填 batches，默认选首项（若有）。
- `loadDetail()`：`const my=++seq`；拉 `/api/history/recent-changes/${bid}/changes?mode&field&change_type`；await 后 `if(my!==seq)return`；写 summary+changes；catch 同；finally 守 loading。401 吞。
- `selectBatch(id)`：set selectedBatchId + 清 filter → loadDetail。`setMode(m)` / `setFilter(f)` → loadDetail。`reset()`：seq++ + 清空。

### 组件（`frontend/src/pages/history/RecentChangesPanel.vue`）
1:1 复刻 index-recent-changes.js：
- 批次下拉（开放批次「🔄 进行中（上次 import 之后）— 改动 N 个货号 · 最近 {takenAt}」；闭合「{takenAt}（{totalLocal} 条 / 改动 {affectedBarcodes} 个货号）」）。
- 5 统计盒（库位变更/型号变更/新增/失效/重新上架，tone 按 count，点击设 filter）+ roundtrip 备注。
- 筛选 chips（全部/仅库位/仅型号/仅新增/仅失效；raw 模式多两枚），count 取 summary，active 高亮。
- 模式切换按钮（折叠净效应 ↔ 展开 raw 事件）。
- 变更列表：collapsed 表（货号/型号/变化/时间，「变化」cell 复刻 renderChangeCell：insert/deactivate/reactivate tag + 库位/型号 from→to 上色）；raw 表（货号/型号/字段/旧值/新值/类型/时间）。cap 300 + 「共 N」备注。
- 行点击 → `emit('drill', barcode)`。
- detailLoading/detailError 子态（不影响 batches 下拉/查询 tab）。
- 颜色仅 token 变量；FIELD_CN / CHANGE_TYPE_CN 中文映射沿用。

### HistoryPage 接线（`frontend/src/pages/history/HistoryPage.vue`，HC-4A-6/7）
- 加 `activeTab` ref（'search'|'batch'），tab 按钮行（货号查询 / 批次记录）。
- 现有 P1-3 内容（搜索框 + 命中态各块）整体包进 `<div v-show="activeTab==='search'">`，**内部不改**。
- 批次 tab：`<div v-if="activeTab==='batch' || batchVisited">`（首次激活置 batchVisited=true，lazy 但切走不卸载）内挂 `<RecentChangesPanel @drill="onDrill" />`，外层 `v-show="activeTab==='batch'"`。
- `onDrill(barcode)`：`activeTab='search'` + `runSearch(barcode)`（input 赋值 + 跑搜索）。

### router / nav 不动（P1 已翻 routeName）。

---

## 测试 / 验收

### 后端（`tests/test_history_recent_changes_api.py`）
- 未登录 → 401。
- `/batches` 命中 → 200，key 恰好 `{ok, batches}`；含 seed 的 import 批次；开放批次（seed 一条 import 后的零散 change）→ 首项 `is_open=true, batch_id=-1`。
- `/<id>/changes` 命中 → 200，key 恰好 `{ok, summary, changes}`；summary 6 字段；changes 行 key 恰好 ChangeRow 7 字段（断言 collapsed 无 old_value/new_value 泄漏、raw 也映射成 from/to/at）。
- `mode=raw` → 行来自 raw 投影；`mode=bad` → 400；非法 batch_id（如 `abc`）→ 400；负 batch_id `-1` → 200（开放批次）。
- filter（field/change_type）透传生效。
- `get_batch_summary`/`get_batch_changes`/`list_recent_imports` 各 mock 抛错 → 500（原子）。
- seed 走 SQLAlchemy（StockpileSnapshot trigger='import' + StockpileChange；参照 `tests/test_recent_changes_service.py`）。

### 前端（vitest）
- `recent-changes-normalize.test.ts`：batches + detail camelCase + null 透传 + 开放批次 totalLocal=null。
- `recentChanges.test.ts`（store）：loadBatches 填 + 默认选首项 / loadDetail 填 summary+changes / 失败填 detailError / 401 吞 / setMode·setFilter 重拉 / **HC-B7：批次 A→B 快切 A 后到不覆盖 B** / reset 作废 pending。
- `RecentChangesPanel.test.ts`：下拉渲染（开放批次文案）/ 统计盒点击设 filter / chips 切换 / 模式切换 collapsed↔raw 列变 / cap 300 + 共 N 备注 / 空批次态 / 行点击 emit('drill', barcode)。
- `HistoryPage.test.ts` 扩展：tab 切换（点批次记录→RecentChangesPanel 渲染、搜索框隐藏；点货号查询→回搜索内容）；batch tab lazy（首次激活才挂）；drill → activeTab 回 search + runSearch 被调；批次 tab 失败不影响查询 tab。

### 守护（HC-4A-9）
- `no-analytics.test.ts` 扫描集加 `stores/recentChanges.ts`；FORBIDDEN 仍 `["/analytics/sku"]` 全通过；断言扫到 recentChanges.ts。

### 最低验收
tab 可切、搜索框仅查询 tab、批次记录最近改动可加载/筛选/切模式/下钻、失败隔离、批次 A→B 不串、旧页深链仍在 ✓

---

## 不做（YAGNI）
不迁扫描批次（4b）；不删旧端点/旧页/深链（4c）；不重构查询 tab 内部；不引表格库。
