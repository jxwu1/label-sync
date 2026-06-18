# 货号历史 Vue Phase 4a 实施 Plan（批次记录 tab 壳 + 最近改动）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `/ui/history` 加一级 tab 壳（货号查询 ↔ 批次记录）+ 迁移批次记录 tab 的「最近改动」子面板，走新建 strict 双端点 `/api/history/recent-changes/{batches,<id>/changes}`。

**Architecture:** additive（旧页/旧 `/recent_changes/*`/「旧版」深链不动，4c 统一退役）。后端单事务 `get_batch_detail`（窗口行只读一次防 READ COMMITTED 撕裂 + 服务端 cap 500 + total_count + batch 存在性 404）。前端独立 `useRecentChangesStore`（三代际守卫 batchesGen/detailSeq/initGen + 成功才置 loaded + 可重试）+ `RecentChangesPanel.vue`（1:1 复刻 index-recent-changes.js）+ HistoryPage tab 壳（查询内容 v-show 零重构，批次 tab lazy）。

**Tech Stack:** Flask + pydantic（extra=forbid）+ Vue 3 + Pinia + TS + vitest + @vue/test-utils + pytest。

**Spec:** `docs/superpowers/specs/2026-06-18-history-vue-phase4a-design.md`（HC-4A-1~9，三轮审查 APPROVE）。

**前置（coder 必读）：**
- 分支 `feat/history-vue-phase4a`。后端 `pytest tests/test_history_recent_changes_api.py -v`；前端 `cd frontend && npx vitest run <file>`；改 schemas_api 跑 `python tools/gen_ts_types.py`。
- 数据源已核：`app/services/recent_changes.py`（`list_recent_imports`/`get_batch_summary`/`get_batch_changes`/`_batch_window`/`_summarize`/`_OPEN_BATCH_ID=-1`）；旧 UI 交互蓝本 `static/js/index-recent-changes.js`；旧页 tab 标记 `templates/partials/_page_history.html`。
- 查询 tab 输入 ref = `q`（HistoryPage.vue:14 `const q = ref("")`，line 77 已有 `q.value = barcode` 模式）。
- store 三代际守卫 + ensureLoaded 范式见 spec store 段，逐字落地。

---

## Task 1: 后端 schema + TS 同步

**Files:** Modify `app/schemas_api.py`；Generated `frontend/src/api/types.gen.ts`

- [ ] **Step 1: 追加 schema**（`SkuTimelineResponse` 之后）
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
    total_count: int
```

- [ ] **Step 2:** `API_MODELS` 追加 `RecentChangesBatchList, RecentChangesDetail`。
- [ ] **Step 3:** `python tools/gen_ts_types.py && python tools/gen_ts_types.py --check`（exit 0）；`grep -c "RecentChangesBatchList\|RecentChangesDetail\|ChangeRow\|RecentChangeBatch" frontend/src/api/types.gen.ts` ≥ 4。
- [ ] **Step 4:** `ruff format app/schemas_api.py && ruff check app/schemas_api.py`。
- [ ] **Step 5: Commit** `git add app/schemas_api.py frontend/src/api/types.gen.ts && git commit -m "feat(history): Phase 4a recent-changes schema + TS 类型"`

---

## Task 2: 后端 service get_batch_detail（单事务单读，TDD）

**Files:** Modify `app/services/recent_changes.py`；Test `tests/test_recent_changes_detail_service.py`（新建）

- [ ] **Step 1: 写失败测试**
参照 `tests/test_recent_changes_service.py` 的 seed（StockpileSnapshot trigger='import' + StockpileChange）。写：
```python
def test_get_batch_detail_single_window_read(monkeypatch):
    # spy _fetch_window_rows 每次 get_batch_detail 只调 1 次（防双 SELECT 撕裂）
    import app.services.recent_changes as rc
    calls = {"n": 0}
    orig = rc._fetch_window_rows
    def counting(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)
    monkeypatch.setattr(rc, "_fetch_window_rows", counting)
    # seed 一个 import 批次 + changes（用现有 seed helper）
    bid = _seed_import_batch_with_changes()
    rc.get_batch_detail(bid, mode="collapsed")
    assert calls["n"] == 1

def test_get_batch_detail_nonexistent_returns_none():
    import app.services.recent_changes as rc
    assert rc.get_batch_detail(999999) is None

def test_get_batch_detail_non_import_snapshot_returns_none():
    # seed 一个 trigger != 'import' 的 snapshot，用其 id
    import app.services.recent_changes as rc
    sid = _seed_snapshot(trigger="manual")
    assert rc.get_batch_detail(sid) is None

def test_get_batch_detail_open_batch_ok():
    import app.services.recent_changes as rc
    _seed_import_then_loose_change()
    d = rc.get_batch_detail(-1, mode="collapsed")
    assert d is not None and "summary" in d and "changes" in d and "total_count" in d

def test_get_batch_detail_cap_and_total():
    import app.services.recent_changes as rc
    bid = _seed_import_batch_with_n_changes(600)   # > _RC_MAX_ROWS
    d = rc.get_batch_detail(bid, mode="raw")
    assert len(d["changes"]) == 500
    assert d["total_count"] == 600
```
> coder：seed helper 复用/扩 `tests/test_recent_changes_service.py`；`_seed_import_batch_with_n_changes` 造 600 条不同 (barcode,field) 的 change（raw 模式不折叠 → 600 行）。

- [ ] **Step 2:** `pytest tests/test_recent_changes_detail_service.py -v` → FAIL。

- [ ] **Step 3: 实现**（`app/services/recent_changes.py` 追加，旧函数不动）
```python
_RC_MAX_ROWS = 500  # 服务端 cap（HC-4A-8）


def _fetch_window_rows(session, start: str, end: str):
    """窗口内**全量** stockpile_changes 行（无 filter，单次 SELECT）。"""
    return session.execute(
        select(
            StockpileChange.product_barcode,
            StockpileChange.field_name,
            StockpileChange.old_value,
            StockpileChange.new_value,
            StockpileChange.change_type,
            StockpileChange.created_at,
        )
        .where(and_(StockpileChange.created_at > start, StockpileChange.created_at <= end))
        .order_by(StockpileChange.created_at)
    ).all()


def _shape_changes(session, rows, mode):
    """collapsed 折叠 / raw 原样 + model join（逻辑搬自 get_batch_changes）。"""
    barcodes = list({r.product_barcode for r in rows})
    models: dict[str, str] = {}
    for i in range(0, len(barcodes), 900):
        chunk = barcodes[i : i + 900]
        for bc, m in session.execute(
            select(Stockpile.product_barcode, Stockpile.product_model).where(
                Stockpile.product_barcode.in_(chunk)
            )
        ).all():
            models[bc] = m

    if mode == "raw":
        return [
            {
                "barcode": r.product_barcode, "model": models.get(r.product_barcode, ""),
                "field": r.field_name, "old_value": r.old_value, "new_value": r.new_value,
                "change_type": r.change_type, "created_at": r.created_at,
            }
            for r in reversed(rows)
        ]
    grouped: dict[tuple[str, str], list] = {}
    for r in rows:
        grouped.setdefault((r.product_barcode, r.field_name), []).append(r)
    result = []
    for (barcode, field), group in grouped.items():
        first_old, last_new, last_type = group[0].old_value, group[-1].new_value, group[-1].change_type
        if first_old == last_new and last_type == "update":
            continue
        result.append({
            "barcode": barcode, "model": models.get(barcode, ""), "field": field,
            "from_value": first_old, "to_value": last_new,
            "change_type": last_type, "latest_at": group[-1].created_at,
        })
    result.sort(key=lambda r: r["latest_at"], reverse=True)
    return result


def get_batch_detail(batch_id, mode="collapsed", filter_field=None, filter_change_type=None):
    """单事务：校验存在 → 算窗口 → 窗口行只读一次 → summary + filter + shape + cap。
    返回 {summary, changes(原始 mode 形状, 截断 _RC_MAX_ROWS), total_count}，不存在/非 import 返 None。"""
    with stockpile_db._session() as session:
        if batch_id != _OPEN_BATCH_ID:
            ok = session.execute(
                select(StockpileSnapshot.id).where(
                    and_(StockpileSnapshot.id == batch_id, StockpileSnapshot.trigger == "import")
                )
            ).scalar_one_or_none()
            if ok is None:
                return None
        start, end = _batch_window(session, batch_id)
        all_rows = _fetch_window_rows(session, start, end)        # 单次读
        summary = _summarize(all_rows)                            # 全量（filter 无关）
        filtered = [
            r for r in all_rows
            if (filter_field is None or r.field_name == filter_field)
            and (filter_change_type is None or r.change_type == filter_change_type)
        ]
        changes_full = _shape_changes(session, filtered, mode)
        total_count = len(changes_full)
        return {"summary": summary, "changes": changes_full[:_RC_MAX_ROWS], "total_count": total_count}
```
> `select`/`and_`/`StockpileSnapshot`/`Stockpile`/`StockpileChange`/`stockpile_db` 文件已 import。`_batch_window` 已支持 `_OPEN_BATCH_ID`。

- [ ] **Step 4:** `pytest tests/test_recent_changes_detail_service.py -v` → 全 PASS；`pytest tests/test_recent_changes_service.py -v`（旧测试不回归）。
- [ ] **Step 5:** ruff + Commit `git commit -m "feat(history): Phase 4a get_batch_detail 单事务单读 + 服务端 cap"`

---

## Task 3: 后端双端点（TDD）

**Files:** Modify `app/routes/history.py`；Test `tests/test_history_recent_changes_api.py`（新建）

- [ ] **Step 1: 写失败测试**（复用 `tests/test_history_extras_api.py` 的 app/auth/no-propagate helper）
覆盖（见 spec 测试节）：未登录 401（两端点）/ `/batches` key=={ok,batches} + 开放批次 is_open/-1 / `/<id>/changes` key=={ok,summary,changes,total_count} + ChangeRow 7 字段（collapsed 无 old/new 泄漏；raw 也映射 from/to/at）/ `mode=raw` / `mode=bad`→400 / `abc`→400 / `-1`→200 / 不存在 999999→404 / 非 import snapshot id→404 / filter 透传 + 未知 field→空 / **spy `get_batch_detail` 经端点（mock 抛错→500）** / **spy `_fetch_window_rows` 每 `/changes` 请求 1 次**。

- [ ] **Step 2:** `pytest tests/test_history_recent_changes_api.py -v` → FAIL（404 路由）。

- [ ] **Step 3: 实现**（`app/routes/history.py` `api_bp`）
```python
_RC_VALID_MODES = ("collapsed", "raw")


@api_bp.get("/recent-changes/batches")
def recent_changes_batches():
    from app.schemas_api import RecentChangesBatchList
    from app.services import recent_changes as rc

    payload = {"ok": True, "batches": rc.list_recent_imports()}
    return jsonify(RecentChangesBatchList.model_validate(payload).model_dump())


def _project_change_row(r: dict, mode: str) -> dict:
    if mode == "raw":
        return {"barcode": r["barcode"], "model": r["model"], "field": r["field"],
                "from_value": r["old_value"], "to_value": r["new_value"],
                "change_type": r["change_type"], "at": r["created_at"]}
    return {"barcode": r["barcode"], "model": r["model"], "field": r["field"],
            "from_value": r["from_value"], "to_value": r["to_value"],
            "change_type": r["change_type"], "at": r["latest_at"]}


@api_bp.get("/recent-changes/<batch_id>/changes")
def recent_changes_detail(batch_id: str):
    from flask import request

    from app.schemas_api import RecentChangesDetail
    from app.services import recent_changes as rc

    try:
        bid = int(batch_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad_batch_id"}), 400
    mode = request.args.get("mode", "collapsed")
    if mode not in _RC_VALID_MODES:
        return jsonify({"ok": False, "error": "bad_mode"}), 400
    field = request.args.get("field") or None
    change_type = request.args.get("change_type") or None

    detail = rc.get_batch_detail(bid, mode=mode, filter_field=field, filter_change_type=change_type)
    if detail is None:
        return jsonify({"ok": False, "error": "batch_not_found"}), 404
    payload = {
        "ok": True,
        "summary": detail["summary"],
        "changes": [_project_change_row(r, mode) for r in detail["changes"]],
        "total_count": detail["total_count"],
    }
    return jsonify(RecentChangesDetail.model_validate(payload).model_dump())
```
> coder：实测 `/api/history/recent-changes/batches` 不被 `<barcode>/...` 动态路由吞（Flask 静态段优先；如冲突调整注册顺序）。`jsonify` `api_bp` 已 import。

- [ ] **Step 4:** `pytest tests/test_history_recent_changes_api.py -v` → 全 PASS；`pytest tests/ -q` 全绿。
- [ ] **Step 5:** ruff + Commit `git commit -m "feat(history): Phase 4a recent-changes 双端点（含 404/cap/单读）"`

---

## Task 4: 前端 VM + normalize（TDD）

**Files:** Create `frontend/src/pages/history/recent-changes-types.ts` / `recent-changes-normalize.ts` / `recent-changes-normalize.test.ts`

- [ ] **Step 1: types**
```typescript
export interface RecentBatchVM { batchId: number; takenAt: string | null; totalLocal: number | null; changeCount: number; affectedBarcodes: number; isOpen: boolean; }
export interface RecentSummaryVM { locationChanges: number; modelChanges: number; inserts: number; deactivates: number; reactivates: number; roundtripCount: number; }
export interface ChangeRowVM { barcode: string; model: string; field: string; fromValue: string | null; toValue: string | null; changeType: string; at: string; }
export interface RecentDetailVM { summary: RecentSummaryVM; changes: ChangeRowVM[]; totalCount: number; }
```

- [ ] **Step 2: 失败测试** `recent-changes-normalize.test.ts`：`normalizeBatches`（snake→camel、开放批次 totalLocal=null、takenAt null）；`normalizeDetail`（summary 6 字段 camel、changes 行 camel、totalCount、null 透传）。

- [ ] **Step 3: 实现** `recent-changes-normalize.ts`
```typescript
import type { RecentChangesBatchList, RecentChangesDetail } from "../../api/types.gen";
import type { RecentBatchVM, RecentDetailVM } from "./recent-changes-types";

export function normalizeBatches(raw: RecentChangesBatchList): RecentBatchVM[] {
  return (raw.batches ?? []).map((b) => ({
    batchId: b.batch_id, takenAt: b.taken_at ?? null, totalLocal: b.total_local ?? null,
    changeCount: b.change_count ?? 0, affectedBarcodes: b.affected_barcodes ?? 0, isOpen: b.is_open,
  }));
}
export function normalizeDetail(raw: RecentChangesDetail): RecentDetailVM {
  const s = raw.summary;
  return {
    summary: {
      locationChanges: s.location_changes ?? 0, modelChanges: s.model_changes ?? 0,
      inserts: s.inserts ?? 0, deactivates: s.deactivates ?? 0,
      reactivates: s.reactivates ?? 0, roundtripCount: s.roundtrip_count ?? 0,
    },
    changes: (raw.changes ?? []).map((c) => ({
      barcode: c.barcode, model: c.model, field: c.field,
      fromValue: c.from_value ?? null, toValue: c.to_value ?? null,
      changeType: c.change_type, at: c.at,
    })),
    totalCount: raw.total_count ?? 0,
  };
}
```

- [ ] **Step 4:** `cd frontend && npx vitest run src/pages/history/recent-changes-normalize.test.ts && npm run typecheck` → PASS+0。
- [ ] **Step 5: Commit** `git commit -m "feat(history): Phase 4a recent-changes VM + normalize"`

---

## Task 5: useRecentChangesStore（TDD，三代际并发）

**Files:** Create `frontend/src/stores/recentChanges.ts` / `recentChanges.test.ts`

- [ ] **Step 1: 失败测试**（mock apiGet；用例见 spec store 测试节，全部写出）：loadBatches 填+自动选首项触发 detail / loadDetail 填 summary+changes+totalCount / detail 失败填 detailError / 401 吞 / setMode·setFilter 重拉 / **HC-B7 detail A→B 后到不覆盖 / reset 作废 pending（含 batches 级）+ loaded=false / ensureLoaded 幂等（首 1+1、await 覆盖两者、二次 0）/ 首次 batches 失败→loaded=false 可重试 / inflight 代际 race（A pending→reset→B→A 完成不清 B inflight→C 不启动）**。

- [ ] **Step 2:** 跑 → FAIL。

- [ ] **Step 3: 实现** `frontend/src/stores/recentChanges.ts`（按 spec store 段逐字；闭包三计数器）
```typescript
import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { RecentChangesBatchList, RecentChangesDetail } from "../api/types.gen";
import { normalizeBatches, normalizeDetail } from "../pages/history/recent-changes-normalize";
import type { RecentBatchVM, RecentSummaryVM, ChangeRowVM } from "../pages/history/recent-changes-types";

export const useRecentChangesStore = defineStore("recentChanges", () => {
  const batches = ref<RecentBatchVM[]>([]);
  const selectedBatchId = ref<number | null>(null);
  const summary = ref<RecentSummaryVM | null>(null);
  const changes = ref<ChangeRowVM[]>([]);
  const totalCount = ref(0);
  const mode = ref<"collapsed" | "raw">("collapsed");
  const filter = ref<{ field: string | null; changeType: string | null }>({ field: null, changeType: null });
  const loading = ref(false);       // batches 级
  const error = ref<string | null>(null);
  const detailLoading = ref(false); // per-batch 级
  const detailError = ref<string | null>(null);
  const loaded = ref(false);
  let inflight = false;
  let batchesGen = 0, detailSeq = 0, initGen = 0;

  async function ensureLoaded() {
    if (loaded.value || inflight) return;
    const my = ++initGen;
    inflight = true;
    try { await loadBatches(); }
    finally { if (my === initGen) inflight = false; }
  }

  async function loadBatches() {
    const my = ++batchesGen;
    loading.value = true; error.value = null;
    try {
      const raw = await apiGet<RecentChangesBatchList>("/api/history/recent-changes/batches");
      if (my !== batchesGen) return;
      batches.value = normalizeBatches(raw);
      loaded.value = true;
      if (batches.value.length) await selectBatch(batches.value[0].batchId);
      else { summary.value = null; changes.value = []; totalCount.value = 0; }
    } catch (e) {
      if (my !== batchesGen) return;
      if (e instanceof UnauthenticatedError) return;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (my === batchesGen) loading.value = false;
    }
  }

  async function loadDetail() {
    if (selectedBatchId.value === null) return;
    const my = ++detailSeq;
    const bid = selectedBatchId.value;
    detailLoading.value = true; detailError.value = null;
    const params = new URLSearchParams({ mode: mode.value });
    if (filter.value.field) params.set("field", filter.value.field);
    if (filter.value.changeType) params.set("change_type", filter.value.changeType);
    try {
      const raw = await apiGet<RecentChangesDetail>(
        `/api/history/recent-changes/${bid}/changes?${params.toString()}`);
      if (my !== detailSeq) return;
      const vm = normalizeDetail(raw);
      summary.value = vm.summary; changes.value = vm.changes; totalCount.value = vm.totalCount;
    } catch (e) {
      if (my !== detailSeq) return;
      if (e instanceof UnauthenticatedError) return;
      detailError.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (my === detailSeq) detailLoading.value = false;
    }
  }

  async function selectBatch(id: number) {
    selectedBatchId.value = id;
    filter.value = { field: null, changeType: null };
    await loadDetail();
  }
  async function setMode(m: "collapsed" | "raw") { mode.value = m; await loadDetail(); }
  async function setFilter(f: { field: string | null; changeType: string | null }) { filter.value = f; await loadDetail(); }
  function reset() {
    batchesGen++; detailSeq++; initGen++; loaded.value = false; inflight = false;
    batches.value = []; selectedBatchId.value = null; summary.value = null;
    changes.value = []; totalCount.value = 0; mode.value = "collapsed";
    filter.value = { field: null, changeType: null };
    loading.value = false; error.value = null; detailLoading.value = false; detailError.value = null;
  }

  return { batches, selectedBatchId, summary, changes, totalCount, mode, filter,
           loading, error, detailLoading, detailError, loaded,
           ensureLoaded, loadBatches, loadDetail, selectBatch, setMode, setFilter, reset };
});
```

- [ ] **Step 4:** 跑 + typecheck → 全 PASS+0。
- [ ] **Step 5: Commit** `git commit -m "feat(history): Phase 4a useRecentChangesStore（三代际并发 + 可重试）"`

---

## Task 6: RecentChangesPanel.vue 组件（TDD）

**Files:** Create `frontend/src/pages/history/RecentChangesPanel.vue` / `RecentChangesPanel.test.ts`

实现 1:1 复刻 `static/js/index-recent-changes.js`（READ 它对照渲染细节）。`emit('drill', barcode)`。`onMounted` → `store.ensureLoaded()`。

- [ ] **Step 1: 失败测试**（mount，stub 不需要；mock store 为 plain object 或真 pinia setActivePinia——参照 HistoryPage.test.ts 范式）：
  - 批次下拉渲染（开放批次「🔄 进行中」文案 / 闭合「{takenAt}（{totalLocal} 条 / 改动 {affectedBarcodes} 个货号）」）。
  - 5 统计盒（库位/型号/新增/失效/重新上架）+ roundtrip 备注；点统计盒 → 调 `store.setFilter`。
  - 筛选 chips 渲染 + 点击 setFilter；模式切换按钮 → `store.setMode`，collapsed↔raw 列数变。
  - collapsed 列表（货号/型号/变化/时间，「变化」cell：insert/deactivate/reactivate tag + 库位/型号 from→to）；raw 列表 7 列。
  - cap：changes.length 截断渲染 300 + 「仅显示前 300 / 共 {totalCount} 条」备注（totalCount>300 时显）。
  - 空批次态「还没有 import 记录」（batches 空）/ detail 空「该批次无实质变更」。
  - 行点击 → `emit('drill', barcode)`。
  - **batches 错误态（store.error）→「重试」按钮，点击调 `store.ensureLoaded`**。
  - **detail 错误态（store.detailError）→「重试当前批次」按钮，点击调 `store.loadDetail`**。
  - `onMounted` → `store.ensureLoaded` 被调。

- [ ] **Step 2:** 跑 → FAIL。

- [ ] **Step 3: 实现**（Vue 模板 + computed；FIELD_CN/CHANGE_TYPE_CN 中文映射沿用；token 色；RENDER_CAP=300）。结构对照 spec 组件段 + index-recent-changes.js renderSummary/renderChips/renderCollapsedList/renderRawList/renderChangeCell。批次下拉 `@change` → `store.selectBatch(Number(...))`；模式按钮 → `store.setMode`；统计盒/chip → `store.setFilter`；行 `@click` → `emit('drill', row.barcode)`。

- [ ] **Step 4:** 跑 + typecheck → 全 PASS+0。
- [ ] **Step 5: Commit** `git commit -m "feat(history): Phase 4a RecentChangesPanel.vue（最近改动 1:1）"`

---

## Task 7: HistoryPage tab 壳 + 接线 + 守卫（TDD）

**Files:** Modify `frontend/src/pages/history/HistoryPage.vue` / `HistoryPage.test.ts` / `no-analytics.test.ts`

- [ ] **Step 1: 失败测试**（HistoryPage.test.ts）：tab 切换（点批次记录→RecentChangesPanel 渲染、搜索框 `q` 隐藏；点货号查询→回搜索内容）；batch tab lazy（首次激活才挂 + 首加载不变量经 store mock 验）；drill → `activeTab='search'` + `q` 值 == barcode + runSearch 被调；批次 tab 失败不影响查询 tab。`no-analytics.test.ts`：扫描集加 `stores/recentChanges.ts` + 断言扫到。

- [ ] **Step 2:** 跑 → FAIL。

- [ ] **Step 3: 实现**
  - HistoryPage.vue：`const activeTab = ref<"search"|"batch">("search")` + `const batchVisited = ref(false)`；tab 按钮行（货号查询/批次记录，点批次记录 set activeTab='batch' + batchVisited=true）；现有查询内容（搜索框 + 命中态全部）整体包 `<div v-show="activeTab==='search'">`（**内部不改**）；批次容器 `<div v-if="batchVisited" v-show="activeTab==='batch'"><RecentChangesPanel @drill="onDrill" /></div>`；`function onDrill(barcode){ activeTab.value='search'; q.value=barcode; runSearch(barcode); }`（runSearch 实际函数名核对，复用 line 77 模式）。
  - no-analytics.test.ts：`HISTORY_STORES` 数组加 `"recentChanges.ts"`。

- [ ] **Step 4:** `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts src/pages/history/no-analytics.test.ts && npm run typecheck` → PASS+0；`npm run test:unit` 全绿。
- [ ] **Step 5: Commit** `git commit -m "feat(history): Phase 4a HistoryPage tab 壳 + 最近改动接线 + 守卫"`

---

## Task 8: 全量验证 + 大批次性能验收

- [ ] **Step 1:** `pytest tests/ -q` 全绿。
- [ ] **Step 2:** `python tools/gen_ts_types.py --check` exit 0。
- [ ] **Step 3:** `cd frontend && npm run test:unit && npm run typecheck && npm run build` 全绿+0+成功。
- [ ] **Step 4:** `ruff check app/ tests/` clean。
- [ ] **Step 5: 大批次性能验收（HC 红队 MEDIUM）**：seed 一个 5000+ 行变更的 import 批次，pytest 计时 `/api/history/recent-changes/<id>/changes`（pydantic+JSON）在可接受范围（< 1s）且 `len(changes)==500`、`total_count==5000+`。若 DB 读取本身成瓶颈 → 记 backlog（SQL LIMIT）。
- [ ] **Step 6: 本地浏览器验收（用户）**：`./dev.ps1 -Frontend` → `/ui/history` 点「批次记录」tab → 选批次/统计盒筛选/切模式/行下钻回查询 tab、搜索框带 barcode；批次 A→B 快切不串；batches/detail 失败有重试。

---

## Self-Review 记录
**Spec 覆盖**：HC-4A-1 additive（不碰旧物=全程）/ 2 双端点+ChangeRow 统一+单事务+cap（T1/2/3）/ 3 batch_id 404（T2/3）/ 4 mode 严格 filter 宽松（T3）/ 5 失败隔离+三代际（T5）/ 6 tab 壳零重构（T7）/ 7 onDrill q.value（T7）/ 8 双层 cap（T2/3/6）/ 9 守卫（T7）。detail 重试（T6）。全部有 task。
**类型一致**：RecentChangesBatchList/RecentChangesDetail/ChangeRow（后端）↔ RecentBatchVM/RecentDetailVM/ChangeRowVM（前端）↔ normalize/store/Panel 贯穿。
**无占位符**：schema/service/endpoint/normalize/store 完整代码；组件给结构+对照 index-recent-changes.js（量大，子段逐一列）。
