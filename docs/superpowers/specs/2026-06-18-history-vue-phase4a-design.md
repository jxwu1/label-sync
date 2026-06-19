# 货号历史页迁移 Vue —— Phase 4a（批次记录 tab 壳 + 最近改动）设计

**状态：** 已审批（2026-06-18，终审 APPROVE）。三轮审查 REQUEST_CHANGES 已处置（一轮 B1-3/mode-filter/onDrill/红队 MEDIUM；二轮 #7 窗口只读一次防 READ COMMITTED 撕裂 / #8 store 双计数器+成功才置 loaded+await 完整链 / #9 onDrill 写死 q.value；三轮 #10 initGen 代际守 inflight / #11 batches 重试按钮 / #12 reset 三代际）。

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

**HC-4A-2（strict 双端点，统一行形状，单事务）：**
- `GET /api/history/recent-changes/batches` → `{ok, batches: list[RecentChangeBatch]}`。
- `GET /api/history/recent-changes/<batch_id>/changes?mode=&field=&change_type=` → `{ok, summary, changes: list[ChangeRow], total_count: int}`。
- **单事务（HC 红队 HIGH）**：summary 与 changes **必须在同一 session/事务内**读出——新增 `recent_changes_service.get_batch_detail(batch_id, mode, field, change_type)`，内部一次开 session、算一次 `_batch_window`、同窗口同时算 summary + changes，返回 `{summary, changes(原始 mode 形状), total_count}`。**禁止**端点分别调 `get_batch_summary` + `get_batch_changes`（各自开 session → 开放批次 -1 两读间写入会让统计与列表不一致）。`get_batch_summary` / `get_batch_changes` 旧函数保留给旧页，不动。
- collapsed（from_value/to_value/latest_at）与 raw（old_value/new_value/created_at）由端点**统一投影**成单一 `ChangeRow`（barcode/model/field/from_value/to_value/change_type/at），strict + TS 干净。
- **服务端 cap（HC 红队 MEDIUM）**：`get_batch_detail` 内 changes 截断到 `_RC_MAX_ROWS = 500`，`total_count` = 截断前全量行数。界定 pydantic 校验 + JSON 传输 + 前端解析（旧 legacy 返回全量、数万行会爆）。前端 DOM 再 cap 300（HC-4A-8）。SQL 级 LIMIT（界定 DB 读取）列 backlog，本期先按 plan 性能验收衡量。
- 响应 key 集合后端测试断言。

**HC-4A-3（batch_id 解析 + 存在性校验，HC 红队 HIGH）：** 开放批次 id = `-1`，Flask `<int:>` 不匹配负数 → 路由用 `<batch_id>`（str）+ 手动 `int()` 解析（含负数），非数字 → **400**。**存在性校验**：合法 batch_id 仅 `-1` **或** 一个 `trigger='import'` 的 StockpileSnapshot id；否则（不存在 / 非 import 类型 snapshot）→ **404**（不能让 `_batch_window` 的 `scalar_one()` 抛 NoResultFound 变 500，也不能把非 import snapshot 当合法窗口返回语义错误数据）。校验在 `get_batch_detail` 内（同事务先查 snapshot 存在且 trigger='import'），端点把「不存在」信号转 404。

**HC-4A-4（mode 严格校验 + filter 宽松透传）：** `mode ∈ {collapsed, raw}`（默认 collapsed），非法 → 400。`field` / `change_type` = **可选窄化过滤，宽松透传**给 service（不校验枚举：未知值 → SQL 无匹配 → 空结果，非错误；UI 只发合法值）。

**HC-4A-5（失败隔离 + HC-B7）：** 批次记录 tab 用**独立 store** `useRecentChangesStore`，独立 loading/error。其失败不影响查询 tab（P1-3）。**per-batch 取数加 HC-B7 单调 request-id**（批次 A→B 快切，A 后到不得覆盖 B 的 summary/changes）；store reset 递增 **batchesGen / detailSeq / initGen 三类代际守卫**（作废全部 pending：batches 取数、detail 取数、ensureLoaded 的 inflight 归属）。401 沿用 `apiGet` 全局语义（吞 `UnauthenticatedError` 不写块内 error）。

**HC-4A-6（tab 壳零重构）：** HistoryPage 加 tab 状态；**现有 P1-3 查询内容整体包进 `v-show="activeTab==='search'"`，不改其内部结构**（零风险）。批次 tab 容器 `v-if` lazy（首次激活才挂 `RecentChangesPanel`，避免无谓请求）。搜索框（含 RECENT chips）仅查询 tab 显示。

**HC-4A-7（下钻）：** 最近改动变更行点击 → `onDrill(barcode)`：①切 `activeTab='search'`；②**`q.value = barcode`**（查询 tab 输入 ref 实为 `q`，HistoryPage.vue:14 `const q = ref("")`）；③再调 `runSearch(barcode)`。现有 `runSearch` **不会**自动更新输入框，必须显式赋 `q.value`，否则用户看到结果但输入框空/旧值。（HistoryPage.vue 内已有 `q.value = barcode` 设值模式可复用。）

**HC-4A-8（双层 cap）：** 端点服务端 cap 500 行（HC-4A-2，界定 payload）+ 返回 `total_count`（全量行数）；前端再 DOM cap 300 行 + 「仅显示前 300 / 共 {total_count} 条 · 用上方筛选缩小」备注（沿用旧 RENDER_CAP）。`total_count > 500`（被服务端截断）时备注用 total_count 真实总数，提示筛选。

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

    detail = rc.get_batch_detail(             # HC-4A-2 单事务；HC-4A-3 不存在返 None
        bid, mode=mode, filter_field=field, filter_change_type=change_type
    )
    if detail is None:                        # 非 -1 且非 import snapshot / 不存在
        return jsonify({"ok": False, "error": "batch_not_found"}), 404
    changes = [_project_change_row(r, mode) for r in detail["changes"]]  # 统一行形状
    payload = {
        "ok": True,
        "summary": detail["summary"],
        "changes": changes,
        "total_count": detail["total_count"],
    }
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

### 新增 service：`recent_changes.get_batch_detail`（单事务，HC-4A-2/3，`app/services/recent_changes.py`）
```python
_RC_MAX_ROWS = 500  # 服务端 cap（HC-4A-8）

def get_batch_detail(batch_id, mode="collapsed", filter_field=None, filter_change_type=None):
    """单 session 内：校验批次存在 → 算窗口 → summary + changes 同窗口同读。
    返回 {summary, changes(原始 mode 形状, 截断 _RC_MAX_ROWS), total_count} 或 None（不存在/非 import）。"""
    with stockpile_db._session() as session:
        # 存在性校验（HC-4A-3）：-1 合法；否则须是 trigger='import' 的 snapshot
        if batch_id != _OPEN_BATCH_ID:
            ok = session.execute(
                select(StockpileSnapshot.id).where(
                    and_(StockpileSnapshot.id == batch_id,
                         StockpileSnapshot.trigger == "import")
                )
            ).scalar_one_or_none()
            if ok is None:
                return None
        start, end = _batch_window(session, batch_id)
        # 红队 HIGH：窗口行**只读一次**（PG READ COMMITTED 下，同 session 两条 SELECT
        # 仍可能读到不同快照 → 统计与列表撕裂）。summary + filter + shape + count + cap
        # 全部从这一份 all_rows 派生。
        all_rows = _fetch_window_rows(session, start, end)     # 单次全量窗口行
        summary = _summarize(all_rows)                         # summary 用全量（filter 无关）
        filtered = [
            r for r in all_rows
            if (filter_field is None or r.field_name == filter_field)
            and (filter_change_type is None or r.change_type == filter_change_type)
        ]                                                      # filter 在内存做，不再二次 SQL
        changes_full = _shape_changes(session, filtered, mode)  # collapsed 折叠 / raw 原样 + model join
        total_count = len(changes_full)
        return {"summary": summary, "changes": changes_full[:_RC_MAX_ROWS], "total_count": total_count}
```
> coder：抽 helper —— `_fetch_window_rows(session, start, end)` 查窗口内**全量** stockpile_changes 行（**无 filter**，单次 SELECT，返回带 field_name/change_type/old_value/new_value/created_at/product_barcode 的行）；`_shape_changes(session, rows, mode)` 做 collapsed 折叠 / raw 原样 + model join。`get_batch_detail` 单次 `_fetch_window_rows` → `_summarize` + 内存 filter + `_shape_changes`。**filter 移到内存**（不再二次 SQL），保证 summary 与 changes 同源一致。**旧 `get_batch_summary` / `get_batch_changes` / 旧路由保持不变**（旧页用，可选内部改调新 helper 但非必须）。`_batch_window` 已接受 `_OPEN_BATCH_ID`。`StockpileSnapshot` / `and_` / `select` 文件已 import。

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
    changes: list[ChangeRow]   # 服务端 cap _RC_MAX_ROWS
    total_count: int           # 截断前全量行数（前端「共 N」备注）
```
`API_MODELS` 追加 `RecentChangesBatchList` + `RecentChangesDetail`，`gen_ts_types` 同步。

> 类型核对：`list_recent_imports` 行（recent_changes.py:90-134）；`get_batch_summary`（:263-289 6 int）；`get_batch_changes` collapsed（:242-252）/raw（:217-227）。`taken_at`/`total_local` 开放批次为 None → `| None`。`model` service 已 `models.get(bc,"")` 兜空串 → str 非空。`from_value/to_value/old_value/new_value` 可为 None → `| None`。

---

## 前端

### VM + normalize（`frontend/src/pages/history/recent-changes-{types,normalize}.ts`）
VM camelCase：`RecentBatchVM`(batchId/takenAt/totalLocal/changeCount/affectedBarcodes/isOpen)、`RecentSummaryVM`(locationChanges/modelChanges/inserts/deactivates/reactivates/roundtripCount)、`ChangeRowVM`(barcode/model/field/fromValue/toValue/changeType/at)、`RecentDetailVM`(summary:RecentSummaryVM, changes:ChangeRowVM[], totalCount:number)。normalize 两个：`normalizeBatches`、`normalizeDetail`（snake→camel，null 透传，totalCount 兜 0）。

### store（`frontend/src/stores/recentChanges.ts`，HC-4A-5；首加载链 HC 红队 B2）
独立 pinia store：
- state：`batches`、`selectedBatchId`、`summary`、`changes`、`totalCount`、`mode`('collapsed')、`filter`({field,changeType})、`loading`/`error`（batches 级）、`detailLoading`/`detailError`（per-batch 级）、`loaded`(bool)、`inflight`(bool, ensureLoaded 防重入)、**闭包级三计数器 `let batchesGen=0; let detailSeq=0; let initGen=0`**（batches / detail / ensureLoaded-inflight 各自代际守护）。
- **`ensureLoaded()`（单一入口，幂等 + 可重试，代际守 inflight）**：`if (loaded || inflight) return;` → **`const my = ++initGen`** → `inflight=true` → `try { await loadBatches(); } finally { if (my === initGen) inflight=false; }`。**finally 必须代际匹配才清 inflight**（红队：否则 A pending→reset→B 启动后，A 的 finally 会错误清掉 B 的 inflight，使 C 重复发请求）。**失败时 `loaded` 保持 false** → 经「重试」再调 ensureLoaded 重载。组件首次激活 onMounted 调；回切 tab 不重载（loaded 已 true）。
- `loadBatches()`：`const my=++batchesGen`；`loading=true; error=null`；拉 `/batches`；**await 后 `if(my!==batchesGen) return`**（reset/重入作废 pending）；填 batches；**成功才 `loaded=true`**；若非空 **`await selectBatch(batches[0].batchId)`**（await 完整链——ensureLoaded 的 Promise 覆盖 batches + 首个 detail）；空则清 summary/changes/totalCount。catch `if(my!==batchesGen) return` + 401 吞 + 写 error（**不置 loaded**，可重试）；finally `if(my===batchesGen) loading=false`。
- `loadDetail()`：`const my=++detailSeq`；`detailLoading=true; detailError=null`；拉 `/${bid}/changes?mode&field&change_type`；await 后 `if(my!==detailSeq) return`；写 summary/changes/totalCount；catch `if(my!==detailSeq) return` + 401 吞 + 写 detailError；finally `if(my===detailSeq) detailLoading=false`。
- `selectBatch(id)`：set selectedBatchId + 清 filter → `await loadDetail()`。`setMode(m)` / `setFilter(f)`：set 后 → `await loadDetail()`。`reset()`：**`batchesGen++; detailSeq++; initGen++`**（三者都作废 pending + 作废在途 ensureLoaded 的 inflight 归属）+ `loaded=false; inflight=false` + 清空全部 state。
- **首加载不变量（测试锁）**：onMounted/ensureLoaded → 恰好 1 次 `/batches` + 1 次 `/changes`，且 ensureLoaded 的 await 在两者都完成后才 resolve；回切 tab → 0 次新请求；**首次 batches 失败 → loaded=false，再次 ensureLoaded 会重试**；**reset 后 pending loadBatches 不回填 state**。

### 组件（`frontend/src/pages/history/RecentChangesPanel.vue`）
1:1 复刻 index-recent-changes.js：
- 批次下拉（开放批次「🔄 进行中（上次 import 之后）— 改动 N 个货号 · 最近 {takenAt}」；闭合「{takenAt}（{totalLocal} 条 / 改动 {affectedBarcodes} 个货号）」）。
- 5 统计盒（库位变更/型号变更/新增/失效/重新上架，tone 按 count，点击设 filter）+ roundtrip 备注。
- 筛选 chips（全部/仅库位/仅型号/仅新增/仅失效；raw 模式多两枚），count 取 summary，active 高亮。
- 模式切换按钮（折叠净效应 ↔ 展开 raw 事件）。
- 变更列表：collapsed 表（货号/型号/变化/时间，「变化」cell 复刻 renderChangeCell：insert/deactivate/reactivate tag + 库位/型号 from→to 上色）；raw 表（货号/型号/字段/旧值/新值/类型/时间）。cap 300 + 「共 N」备注。
- 行点击 → `emit('drill', barcode)`。
- **`onMounted` → `store.ensureLoaded()`**（组件 lazy v-if 挂载即首次激活；幂等闸保证回切不重载，首加载链 = ensureLoaded→loadBatches→自动选首项→loadDetail）。
- **batches 级状态**：`store.loading` → 「批次加载中…」；**`store.error` → 错误条 + 「重试」按钮（点击 `store.ensureLoaded()`，失败后 loaded=false 故可重发）**；成功且 batches 空 → 「还没有 import 记录」。
- detailLoading/detailError 子态（per-batch，不影响 batches 下拉/查询 tab）；**`detailError` → 「重试当前批次」按钮（→ `store.loadDetail()` 重拉当前 batch+mode+filter）**（终审非阻断建议收编）。
- 颜色仅 token 变量；FIELD_CN / CHANGE_TYPE_CN 中文映射沿用。

### HistoryPage 接线（`frontend/src/pages/history/HistoryPage.vue`，HC-4A-6/7）
- 加 `activeTab` ref（'search'|'batch'），tab 按钮行（货号查询 / 批次记录）。
- 现有 P1-3 内容（搜索框 + 命中态各块）整体包进 `<div v-show="activeTab==='search'">`，**内部不改**。
- 批次 tab：`<div v-if="activeTab==='batch' || batchVisited">`（首次激活置 batchVisited=true，lazy 但切走不卸载）内挂 `<RecentChangesPanel @drill="onDrill" />`，外层 `v-show="activeTab==='batch'"`。
- `onDrill(barcode)`（HC-4A-7）：`activeTab='search'`；**`q.value = barcode`**（ref `q`，HistoryPage.vue:14）；再 `runSearch(barcode)`。

### router / nav 不动（P1 已翻 routeName）。

---

## 测试 / 验收

### 后端（`tests/test_history_recent_changes_api.py`）
- 未登录 → 401（两端点）。
- `/batches` 命中 → 200，key 恰好 `{ok, batches}`；含 seed 的 import 批次；开放批次（seed 一条 import 后的零散 change）→ 首项 `is_open=true, batch_id=-1`。
- `/<id>/changes` 命中 → 200，key 恰好 `{ok, summary, changes, total_count}`；summary 6 字段；changes 行 key 恰好 ChangeRow 7 字段（断言 collapsed 无 old_value/new_value 泄漏、raw 也映射成 from/to/at）。
- `mode=raw` → 行来自 raw 投影；`mode=bad` → 400。
- **batch_id 校验（HC-4A-3）**：非数字 `abc` → 400；负 `-1` → 200（开放批次）；**不存在的 id（如 999999）→ 404**；**非 import snapshot id（seed 一个 trigger≠'import' 的 snapshot，用它的 id）→ 404**（不能 500、不能返语义错误数据）。
- **单事务 + 窗口只读一次（HC-4A-2，红队 HIGH）**：`/changes` 经 `get_batch_detail`；**spy `_fetch_window_rows` 每请求恰好调用 1 次**（summary 与 changes 同源 all_rows，无二次 SELECT 快照漂移）；断言 summary 计数与 changes 口径一致（同窗口）。
- **服务端 cap（HC-4A-8）**：seed > 500 行变更的批次 → `len(changes) == 500` 且 `total_count` == 真实全量数（> 500）。
- filter（field/change_type）宽松透传生效；未知 field 值 → 空 changes（非 400）。
- 原子失败：mock `get_batch_detail`（changes 端点）/ `list_recent_imports`（batches 端点）抛错 → 500。
- seed 走 SQLAlchemy（StockpileSnapshot trigger='import' + StockpileChange；参照 `tests/test_recent_changes_service.py`）。

### 前端（vitest）
- `recent-changes-normalize.test.ts`：batches + detail camelCase + null 透传 + 开放批次 totalLocal=null。
- `recentChanges.test.ts`（store）：loadBatches 填 + **自动选首项触发 loadDetail** / loadDetail 填 summary+changes+totalCount / 失败填 detailError / 401 吞 / setMode·setFilter 重拉 / **HC-B7：批次 A→B 快切 A 后到不覆盖 B** / reset 作废 pending（**含 batches 级**：reset 后 pending loadBatches resolve 不回填）+ `loaded=false` / **`ensureLoaded` 幂等：首次调 → 恰好 1 次 batches + 1 次 changes 且 await 在两者完成后 resolve；二次调 → 0 次新请求** / **首次 batches 失败 → `loaded=false`，再次 ensureLoaded 重试（再发请求）** / **inflight 代际race：A pending → reset → ensureLoaded(B) 启动 → A resolve（A 的 finally 因 initGen 不匹配不清 B 的 inflight）→ 再调 ensureLoaded 不启动 C（B 仍 inflight）**。
- `RecentChangesPanel.test.ts`：下拉渲染（开放批次文案）/ 统计盒点击设 filter / chips 切换 / 模式切换 collapsed↔raw 列变 / cap 300 + 共 N 备注 / 空批次态 / 行点击 emit('drill', barcode) / **batches 错误态显「重试」按钮，点击调 `store.ensureLoaded`（重发）**。
- `HistoryPage.test.ts` 扩展：tab 切换（点批次记录→RecentChangesPanel 渲染、搜索框隐藏；点货号查询→回搜索内容）；**batch tab lazy + 首加载不变量（首次激活恰好 1 batches + 1 changes；回切 0 新请求）**；drill → activeTab 回 search + **输入 ref 被设为 barcode** + runSearch 被调；批次 tab 失败不影响查询 tab。

### 性能验收（HC 红队 MEDIUM，plan 落地）
plan 加一步：seed 一个**大批次**（如 5000+ 行变更），实测 `/changes` 端点响应（pydantic 校验 + JSON 序列化）在可接受范围（如 < 1s），且 `len(changes)==500` 截断生效。若实测 DB 读取本身成瓶颈 → 记 backlog 改 SQL 级 LIMIT（本期服务端 cap 已界定 pydantic/JSON/传输）。

### 守护（HC-4A-9）
- `no-analytics.test.ts` 扫描集加 `stores/recentChanges.ts`；FORBIDDEN 仍 `["/analytics/sku"]` 全通过；断言扫到 recentChanges.ts。

### 最低验收
tab 可切、搜索框仅查询 tab、批次记录最近改动可加载/筛选/切模式/下钻、失败隔离、批次 A→B 不串、旧页深链仍在 ✓

---

## 不做（YAGNI）
不迁扫描批次（4b）；不删旧端点/旧页/深链（4c）；不重构查询 tab 内部；不引表格库。

---

## 审查修订记录（REQUEST_CHANGES → 已处置，2026-06-18）

| # | 类型 | 发现 | 处置 |
|---|---|---|---|
| 1 | BLOCKER | summary/changes 各自开 session，开放批次 -1 两读间写入 → 统计与列表不一致 | HC-4A-2：新增单事务 `get_batch_detail`，同 session 同窗口算 summary+changes；端点不再分调；旧函数留旧页 |
| 2 | BLOCKER | 首加载链不完整（谁触发首次 loadDetail 未定） | HC-4A-5 + store：`ensureLoaded`（幂等闸）单一入口 → loadBatches 自动选首项 → loadDetail；组件 onMounted 调；测试锁首激活 1+1、回切 0 |
| 3 | BLOCKER | batch_id 仅校验非法字符串；不存在 id → NoResultFound 500；非 import snapshot id 当合法窗口 | HC-4A-3：get_batch_detail 内校验「-1 或 trigger='import' snapshot」，否则端点 404；测试覆盖不存在/非 import |
| 4 | 需明确 | HC 标题「mode/filter 校验」但只校 mode | HC-4A-4：mode 严格 400 + filter 宽松透传（明确语义） |
| 5 | 需明确 | onDrill 未说设输入框 | HC-4A-7：onDrill 先 `query.value=barcode` 再 runSearch |
| 6 | 红队 MEDIUM | DOM cap 300 不限 DB/pydantic/JSON；数万行批次 | HC-4A-8：服务端 cap 500 + total_count；plan 加大批次性能验收；SQL LIMIT 列 backlog |

### 第二轮审查（REQUEST_CHANGES → 已处置，2026-06-18）

| # | 类型 | 发现 | 处置 |
|---|---|---|---|
| 7 | BLOCKER（红队 HIGH） | get_batch_detail 仍调两次 `_fetch_window_rows`；PG READ COMMITTED 下同 session 两 SELECT 仍可能不同快照 → 撕裂 | 改**只读一次** all_rows，summary + 内存 filter + shape + count + cap 全从 all_rows 派生；测试 spy `_fetch_window_rows` 每请求 1 次 |
| 8 | BLOCKER | store 并发：①loaded 请求前置→失败不可重试 ②reset 只守 detail，pending loadBatches 仍回填 ③loadBatches 未 await selectBatch | 双计数器 `batchesGen`/`detailSeq`（reset 都 ++）；**成功才置 loaded**（失败可重试）+ ensureLoaded inflight 防重入；loadBatches **await selectBatch**（init Promise 覆盖完整链）；测试锁重试 + reset 作废 batches |
| 9 | 文档 | onDrill 占位 `query.value` + 「coder 核实」 | 写死 `q.value = barcode`（ref 实为 `q`，HistoryPage.vue:14） |

### 第三轮审查（REQUEST_CHANGES → 已处置，2026-06-18）

| # | 类型 | 发现 | 处置 |
|---|---|---|---|
| 10 | BLOCKER | `inflight` 无代际：A pending→reset→B 启动→A 的 finally 错误清 B 的 inflight→C 可重发 | 加 `initGen`；ensureLoaded `const my=++initGen`，finally **`if(my===initGen)`** 才清 inflight；reset `initGen++`；测试锁此 race |
| 11 | 契约缺失 | spec 说「可重试」但组件/测试无重试按钮 | 组件加 batches 错误态 + 「重试」按钮（→ ensureLoaded）；RecentChangesPanel 测试补 |
| 12 | 契约缺失 | HC-4A-5 仍写 reset 递增单 seq | 同步为 batchesGen/detailSeq/initGen 三代际守卫 |
