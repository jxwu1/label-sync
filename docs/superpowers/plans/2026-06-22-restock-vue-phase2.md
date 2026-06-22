# 补货页 Vue Phase 2（只读 drawer 明细）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补货页 `/ui/restock` 命中行点击内联展开只读 drawer 明细（财务/库存/盈亏/销售概况/紧迫分四维），行为对旧 `renderDrawer` 只读部分 1:1。

**Architecture:** 后端新增 1 个 strict 瘦端点 `GET /api/restock/<barcode>/detail`（复用 `compute_restock_snapshot` 物化单行 + 显式嵌套投影）；前端 keyed Pinia store 按 barcode 分区缓存/并发，`RestockDrawer.vue` 自取数渲染，`RestockTable` 行内联展开（click + keydown.self + aria-expanded，子按钮 click.stop）。列表 `items` 端点 / `RestockItem` 冻结不动。

**Tech Stack:** Flask + pydantic v2（后端）、Vue 3 + Pinia + vue-router + TypeScript + Vitest（前端）、Playwright（e2e）。

**Spec:** `docs/superpowers/specs/2026-06-22-restock-vue-phase2-design.md`（Approved）。实现前通读；本计划契约值以 spec 为准。

**纪律：** 全程在 `feat/restock-vue-phase2` 分支（已建，spec 已提交其上），squash merge 回 main。周一 14:00 scraper 窗口禁 push main（feat 分支 push 安全）。

---

## 文件结构

**后端：**
- Modify `app/schemas_api.py` — 加 `RestockDetailUrgencyBreakdown` / `RestockDetail` / `RestockDetailResponse`，注册进 `API_MODELS`（:526）
- Modify `app/routes/restock.py` — 加 `_BD_KEYS` / `_DETAIL_FLAT_KEYS` / `_project_detail` + `GET /<barcode>/detail` 端点
- Modify `frontend/src/api/types.gen.ts` — `gen_ts_types.py` 生成（不手改）
- Modify `tests/test_restock_api.py` — detail schema + 投影 + 端点 + 404 + 结构性 mock 测试

**前端：**
- Modify `frontend/src/api/client.ts` — 加 `ApiError extends Error { status }`
- Create `frontend/src/pages/restock/drawer-cells.ts` + `.test.ts` — drawer 展示纯函数
- Create `frontend/src/stores/restockDetail.ts` + `.test.ts` — keyed Pinia store
- Create `frontend/src/pages/restock/RestockDrawer.vue` + `.test.ts` — drawer 组件
- Modify `frontend/src/pages/restock/RestockTable.vue` + `.test.ts` — 行展开 + 子按钮 stop + 键盘
- Modify `frontend/src/pages/restock/RestockPage.vue` + `.test.ts` — `expandedBarcode` 编排
- Modify `frontend/src/pages/restock/types.ts` — re-export `RestockDetail`

**e2e：**
- Modify `e2e/test_restock_smoke.py` — 点行 → drawer 现

---

## 阶段 A：后端 strict detail 端点

### Task 1: RestockDetail schema（含独立嵌套 breakdown）

**Files:**
- Modify: `app/schemas_api.py`
- Test: `tests/test_restock_api.py`

- [ ] **Step 1: 写 schema 失败测试**

```python
# tests/test_restock_api.py — 追加（顶部已 from app.schemas_api import ... 集中）
from app.schemas_api import (
    RestockDetail,
    RestockDetailResponse,
    RestockDetailUrgencyBreakdown,
)


def _full_breakdown():
    return {
        "velocity": 25.0, "cover": 28.0, "recency": 8.0, "margin": 22.0,
        "demand_validity": 0.75, "velocity_pctile": 0.83, "margin_pctile": 0.61,
    }


def _full_detail():
    return {
        "barcode": "5201234567890",
        "master_sale_price_eur": 6.0, "sale_net_avg": 5.8,
        "retail_price_observed": 5.5, "retail_price_estimate": 6.2,
        "last_purchase_unit_price": 3.0, "master_stock_price_eur": 3.2,
        "margin_source": "purchase", "margin_pct": 35.0,
        "qty_total": 100, "inventory_sale_value_eur": 600.0,
        "inventory_cost_value_eur": 320.0, "weeks_of_cover": 2.0,
        "realized_profit_eur": 500.0, "lifetime_invested_eur": 320.0,
        "lifetime_purchase_qty": 60, "lifetime_sale_revenue_eur": 800.0,
        "lifetime_sale_qty": 70, "net_cashflow_eur": 480.0,
        "inventory_imbalance_pct": 12.0, "is_history_truncated": False,
        "first_event_at": "2021-07-01",
        "total_qty": 700, "n_active_weeks_26w": 18,
        "weekly_velocity": 12.5, "weekly_revenue": 80.0,
        "retail_qty_26w": 3, "retail_revenue_26w": 16.5, "retail_share_26w": 0.04,
        "urgency_score": 88.5, "urgency_breakdown": _full_breakdown(),
    }


def test_restock_detail_full_ok():
    m = RestockDetail.model_validate(_full_detail())
    assert m.urgency_breakdown.velocity_pctile == 0.83
    assert m.total_qty == 700


def test_restock_detail_breakdown_none_ok():
    d = _full_detail(); d["urgency_breakdown"] = None
    assert RestockDetail.model_validate(d).urgency_breakdown is None


@pytest.mark.parametrize("field", [
    "total_qty", "lifetime_purchase_qty", "lifetime_sale_qty",
    "lifetime_sale_revenue_eur", "n_active_weeks_26w",
    "weekly_velocity", "weekly_revenue", "is_history_truncated",
])
def test_restock_detail_nonnull_fields_reject_none(field):
    d = _full_detail(); d[field] = None
    with pytest.raises(ValidationError):
        RestockDetail.model_validate(d)


@pytest.mark.parametrize("field", [
    "velocity", "cover", "recency", "margin",
    "demand_validity", "velocity_pctile", "margin_pctile",
])
def test_restock_breakdown_subfields_reject_none(field):
    bd = _full_breakdown(); bd[field] = None
    with pytest.raises(ValidationError):
        RestockDetailUrgencyBreakdown.model_validate(bd)


def test_restock_breakdown_rejects_extra_key():
    bd = _full_breakdown(); bd["margin_missing"] = False
    with pytest.raises(ValidationError):
        RestockDetailUrgencyBreakdown.model_validate(bd)


def test_restock_detail_response_ok():
    m = RestockDetailResponse.model_validate({"ok": True, "detail": _full_detail()})
    assert m.ok is True and m.detail.barcode == "5201234567890"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_restock_api.py -k "restock_detail or restock_breakdown" -v`
Expected: FAIL（ImportError: RestockDetail）

- [ ] **Step 3: 加 schema**

```python
# app/schemas_api.py — 追加（保持文件 import 风格；顶部已有 Literal 等）
class RestockDetailUrgencyBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    velocity: float
    cover: float
    recency: float
    margin: float
    demand_validity: float
    velocity_pctile: float
    margin_pctile: float


class RestockDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    barcode: str
    # 财务快照
    master_sale_price_eur: float | None
    sale_net_avg: float | None
    retail_price_observed: float | None
    retail_price_estimate: float | None
    last_purchase_unit_price: float | None
    master_stock_price_eur: float | None
    margin_source: str | None
    margin_pct: float | None
    # 库存
    qty_total: int | None
    inventory_sale_value_eur: float | None
    inventory_cost_value_eur: float | None
    weeks_of_cover: float | None
    # 累计盈亏（三恒非空 + 余可空）
    realized_profit_eur: float | None
    lifetime_invested_eur: float | None
    lifetime_purchase_qty: int
    lifetime_sale_revenue_eur: float
    lifetime_sale_qty: int
    net_cashflow_eur: float | None
    inventory_imbalance_pct: float | None
    is_history_truncated: bool
    first_event_at: str | None
    # 销售概况（§4 口径）
    total_qty: int
    n_active_weeks_26w: int
    weekly_velocity: float
    weekly_revenue: float
    retail_qty_26w: int
    retail_revenue_26w: float
    retail_share_26w: float
    # 紧迫分
    urgency_score: float | None
    urgency_breakdown: RestockDetailUrgencyBreakdown | None


class RestockDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    detail: RestockDetail
```

`API_MODELS`（:526）追加 `RestockDetailResponse`（嵌套 RestockDetail / RestockDetailUrgencyBreakdown 会被一并导出）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_restock_api.py -k "restock_detail or restock_breakdown" -v`
Expected: PASS（全部 parametrize 分支）

- [ ] **Step 5: Commit**

```bash
git add app/schemas_api.py tests/test_restock_api.py
git commit -m "feat(restock): RestockDetail strict schema（独立嵌套 breakdown + 收紧 nullability）"
```

---

### Task 2: 投影 + GET /api/restock/<barcode>/detail

**Files:**
- Modify: `app/routes/restock.py`
- Test: `tests/test_restock_api.py`

- [ ] **Step 1: 写投影 key 集测试（喂满 10 键 breakdown，断言丢 3 键）**

```python
# tests/test_restock_api.py — 追加
from app.routes.restock import _BD_KEYS, _DETAIL_FLAT_KEYS, _project_detail


def test_project_detail_drops_fat_and_3_breakdown_keys():
    fat = {
        **_full_detail(),
        "model": "X", "supplier_id": "GR1", "lifespan_days": 99,  # drawer 外胖字段
    }
    # breakdown 喂满真实 10 键（含要丢的 3 个）
    fat["urgency_breakdown"] = {
        **_full_breakdown(),
        "margin_missing": False, "margin_source": "purchase", "margin_price_source": "master",
    }
    out = _project_detail(fat)
    assert set(out.keys()) == set(_DETAIL_FLAT_KEYS) | {"urgency_breakdown"}
    assert "model" not in out and "lifespan_days" not in out
    assert set(out["urgency_breakdown"].keys()) == set(_BD_KEYS)
    for dropped in ("margin_missing", "margin_source", "margin_price_source"):
        assert dropped not in out["urgency_breakdown"]


def test_project_detail_breakdown_none_passthrough():
    d = {**_full_detail(), "urgency_breakdown": None}
    assert _project_detail(d)["urgency_breakdown"] is None
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_restock_api.py -k project_detail -v`
Expected: FAIL（ImportError: _project_detail）

- [ ] **Step 3: 加投影 + 端点**

```python
# app/routes/restock.py — 顶部 import 合并加 RestockDetail 等 + compute_restock_snapshot
from app.schemas_api import RestockDetail, RestockDetailResponse, RestockDetailUrgencyBreakdown
from app.services.analytics.restock_calc import compute_restock_snapshot

_BD_KEYS = tuple(RestockDetailUrgencyBreakdown.model_fields.keys())
_DETAIL_FLAT_KEYS = tuple(
    k for k in RestockDetail.model_fields.keys() if k != "urgency_breakdown"
)


def _project_detail(row: dict) -> dict:
    out = {k: row.get(k) for k in _DETAIL_FLAT_KEYS}
    bd = row.get("urgency_breakdown")
    out["urgency_breakdown"] = {k: bd.get(k) for k in _BD_KEYS} if bd else None
    return out


@api_bp.get("/<barcode>/detail")
def api_detail(barcode: str):
    row = compute_restock_snapshot(barcode)
    if row is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    payload = {"ok": True, "detail": _project_detail(row)}
    return jsonify(RestockDetailResponse.model_validate(payload).model_dump())
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_restock_api.py -k project_detail -v`
Expected: PASS

- [ ] **Step 5: 写端点测试（seed 200 形状 + 404 精确 + 结构性 mock）**

```python
# tests/test_restock_api.py — 追加
def test_api_detail_seeded_returns_envelope(real_app):
    from datetime import datetime
    from app.models import SkuSummary, get_session
    from app.services.analytics.summary import clear_list_sku_summary_cache

    as_of = datetime.now().date().isoformat()
    fat = {**_full_detail(), "model": "X", "lifespan_days": 9}  # 胖 payload
    fat["urgency_breakdown"] = {
        **_full_breakdown(),
        "margin_missing": False, "margin_source": "purchase", "margin_price_source": "master",
    }
    with get_session() as s:
        s.merge(SkuSummary(product_barcode="5201234567890", as_of=as_of, payload=fat))
    clear_list_sku_summary_cache()
    try:
        resp = real_app.test_client().get(
            "/api/restock/5201234567890/detail",
            headers={"X-Upload-Token": "test-token-123"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["detail"]["barcode"] == "5201234567890"
        assert "margin_missing" not in data["detail"]["urgency_breakdown"]
    finally:
        clear_list_sku_summary_cache()


def test_api_detail_unknown_barcode_404(real_app):
    resp = real_app.test_client().get(
        "/api/restock/NOSUCH/detail", headers={"X-Upload-Token": "test-token-123"}
    )
    assert resp.status_code == 404
    assert resp.get_json() == {"ok": False, "error": "not_found"}


def test_api_detail_calls_snapshot_once(real_app, monkeypatch):
    calls = {"n": 0}

    def _fake(barcode):
        calls["n"] += 1
        return _full_detail()

    monkeypatch.setattr("app.routes.restock.compute_restock_snapshot", _fake)
    resp = real_app.test_client().get(
        "/api/restock/5201234567890/detail",
        headers={"X-Upload-Token": "test-token-123"},
    )
    assert resp.status_code == 200
    assert calls["n"] == 1  # 结构性：只调一次，非毫秒断言
```

- [ ] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_restock_api.py -v`
Expected: PASS（全部）

- [ ] **Step 7: Commit**

```bash
git add app/routes/restock.py tests/test_restock_api.py
git commit -m "feat(restock): GET /api/restock/<bc>/detail（compute_restock_snapshot + 显式嵌套投影 + 404）"
```

---

### Task 3: 生成 TS 类型

**Files:**
- Modify: `frontend/src/api/types.gen.ts`（生成）

- [ ] **Step 1: 重新生成**

Run: `python tools/gen_ts_types.py`
Expected: `types.gen.ts` 出现 `RestockDetail` / `RestockDetailUrgencyBreakdown` / `RestockDetailResponse`

- [ ] **Step 2: 漂移检查**

Run: `python tools/gen_ts_types.py --check`
Expected: 退出码 0

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/types.gen.ts
git commit -m "chore(restock): gen_ts_types 同步 RestockDetail 等类型"
```

---

## 阶段 B：前端 client + 纯函数

### Task 4: ApiError（暴露 status，向后兼容）

**Files:**
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`（Create）

- [ ] **Step 1: 写测试**

```ts
// frontend/src/api/client.test.ts
import { describe, it, expect } from "vitest";
import { ApiError } from "./client";

describe("ApiError", () => {
  it("带 status 且仍是 Error 子类（向后兼容）", () => {
    const e = new ApiError(404, "API 404: /x");
    expect(e).toBeInstanceOf(Error);
    expect(e.status).toBe(404);
    expect(e.message).toBe("API 404: /x");
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL（无 ApiError 导出）

- [ ] **Step 3: 实现**

```ts
// frontend/src/api/client.ts — 加导出 + 改 !res.ok 分支
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}
// apiGet 内：将 `if (!res.ok) throw new Error(...)` 改为：
//   if (!res.ok) throw new ApiError(res.status, `API ${res.status}: ${path}`);
```

> 仅改 `!res.ok` 分支抛 `ApiError`；401/redirect/HTML 分支不变（仍 `UnauthenticatedError`）。`ApiError extends Error`，既有 `catch (e) { (e as Error).message }` 不破。

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/api/client.test.ts
cd .. && git add frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "feat(api): ApiError 暴露 HTTP status（向后兼容 Error）"
```

---

### Task 5: drawer-cells.ts（drawer 展示纯函数）

**Files:**
- Create: `frontend/src/pages/restock/drawer-cells.ts` + `.test.ts`

- [ ] **Step 1: 写测试（移植 renderDrawer 分档；销售概况口径准确）**

```ts
import { describe, it, expect } from "vitest";
import { profitStatus, retailPriceLine, cashflowImbalance, scoreSegments } from "./drawer-cells";

describe("drawer-cells", () => {
  it("profitStatus 四档（restock.js:430-446）", () => {
    expect(profitStatus(null, 0)).toEqual({ cls: "unknown", label: "缺成本" });
    expect(profitStatus(5, 0)).toEqual({ cls: "good", label: "已回本" });
    expect(profitStatus(-3, 10)).toEqual({ cls: "mid", label: "压货中" });   // rp+inv>0
    expect(profitStatus(-30, 10)).toEqual({ cls: "bad", label: "账面亏损" }); // rp+inv≤0
  });
  it("retailPriceLine observed/estimate 分支（restock.js:420-429）", () => {
    expect(retailPriceLine(5.5, 6.2, 3).kind).toBe("both");
    expect(retailPriceLine(5.5, null, 3).kind).toBe("observed");
    expect(retailPriceLine(null, 6.2, 0).kind).toBe("estimate");
    expect(retailPriceLine(null, null, 0).kind).toBe("none");
  });
  it("cashflowImbalance >30% 警告（restock.js:451-455）", () => {
    expect(cashflowImbalance(35).warn).toBe(true);
    expect(cashflowImbalance(30).warn).toBe(false);
    expect(cashflowImbalance(null).warn).toBe(false);
  });
  it("scoreSegments 段宽与占比（restock.js:159-168）", () => {
    const segs = scoreSegments({ velocity: 30, cover: 15, recency: 5, margin: 0 } as any);
    expect(segs.map((s) => s.widthPct)).toEqual([30, 30, 10, 30]); // 段宽=总分占比
    expect(segs[0].fillPct).toBe(100); // 30/30
    expect(segs[3].fillPct).toBe(0);   // 0/30
  });
});
```

- [ ] **Step 2: 运行确认失败 → Step 3 实现**

```ts
// frontend/src/pages/restock/drawer-cells.ts
import type { RestockDetailUrgencyBreakdown } from "../../api/types.gen";

export function profitStatus(
  rp: number | null | undefined, inv: number | null | undefined,
): { cls: string; label: string } {
  if (rp === null || rp === undefined) return { cls: "unknown", label: "缺成本" };
  const i = inv ?? 0;
  if (rp > 0) return { cls: "good", label: "已回本" };
  if (rp + i > 0) return { cls: "mid", label: "压货中" };
  return { cls: "bad", label: "账面亏损" };
}

export function retailPriceLine(
  observed: number | null | undefined, estimate: number | null | undefined,
  retailQty26w: number,
): { kind: "both" | "observed" | "estimate" | "none"; observed: number | null; estimate: number | null; qty: number } {
  const o = observed ?? null, e = estimate ?? null;
  const kind = o != null && e != null ? "both" : o != null ? "observed" : e != null ? "estimate" : "none";
  return { kind, observed: o, estimate: e, qty: retailQty26w };
}

export function cashflowImbalance(imb: number | null | undefined): { warn: boolean; pct: number | null } {
  return { warn: imb != null && imb > 30, pct: imb ?? null };
}

export function scoreSegments(bd: RestockDetailUrgencyBreakdown) {
  const defs = [
    { val: bd.velocity, max: 30, cls: "v", label: `销额 ${bd.velocity}/30` },
    { val: bd.cover, max: 30, cls: "c", label: `库存 ${bd.cover}/30` },
    { val: bd.recency, max: 10, cls: "r", label: `距进货 ${bd.recency}/10` },
    { val: bd.margin, max: 30, cls: "m", label: `毛利 ${bd.margin}/30` },
  ];
  return defs.map((d) => ({
    ...d,
    widthPct: d.max, // 段宽按总分占比（销30 库30 距10 利30）
    fillPct: Math.max(0, Math.min(100, (d.val / d.max) * 100)),
  }));
}
```

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/drawer-cells.test.ts
cd .. && git add frontend/src/pages/restock/drawer-cells.* && git commit -m "feat(restock-ui): drawer-cells 展示纯函数（盈亏/零售价/现金流/四维段）"
```

---

## 阶段 C：keyed store

### Task 6: restockDetail keyed Pinia store

**Files:**
- Create: `frontend/src/stores/restockDetail.ts` + `.test.ts`

- [ ] **Step 1: 写测试（缓存命中/inflight 合并/A-B 隔离/404/500/401）**

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
vi.mock("../api/client", () => ({
  apiGet: vi.fn(),
  ApiError: class extends Error { constructor(public status: number, m: string){ super(m); } },
  UnauthenticatedError: class extends Error {},
}));
import { apiGet, ApiError, UnauthenticatedError } from "../api/client";
import { useRestockDetailStore } from "./restockDetail";

const detail = (bc: string) => ({ barcode: bc, urgency_breakdown: null });

beforeEach(() => { setActivePinia(createPinia()); vi.mocked(apiGet).mockReset(); });

describe("restockDetail store", () => {
  it("缓存命中不重拉", async () => {
    vi.mocked(apiGet).mockResolvedValue({ ok: true, detail: detail("b1") } as any);
    const s = useRestockDetailStore();
    await s.load("b1");
    await s.load("b1");
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(s.entries["b1"]).toBe("ready");
    expect(s.cache["b1"].barcode).toBe("b1");
  });
  it("inflight 合并同 SKU 并发（只发一次）", async () => {
    let resolve: (v: any) => void;
    vi.mocked(apiGet).mockReturnValue(new Promise((r) => { resolve = r; }) as any);
    const s = useRestockDetailStore();
    const p1 = s.load("b1"); const p2 = s.load("b1");
    resolve!({ ok: true, detail: detail("b1") });
    await Promise.all([p1, p2]);
    expect(apiGet).toHaveBeenCalledTimes(1);
  });
  it("A/B 隔离：A 迟到只填 cache[A]，不动当前 B", async () => {
    let resolveA: (v: any) => void;
    vi.mocked(apiGet).mockImplementation((path: string) => {
      if (path.includes("A")) return new Promise((r) => { resolveA = r; }) as any;
      return Promise.resolve({ ok: true, detail: detail("B") }) as any;
    });
    const s = useRestockDetailStore();
    s.load("A");                 // A 挂起
    await s.load("B");           // B 完成
    expect(s.entries["B"]).toBe("ready");
    resolveA!({ ok: true, detail: detail("A") }); // A 迟到
    await Promise.resolve();
    expect(s.cache["A"].barcode).toBe("A"); // 只填自己 key
    expect(s.cache["B"].barcode).toBe("B"); // B 不被污染
  });
  it("404 → missing；500 → error 不缓存可重试；401 → 中性不写错", async () => {
    const s = useRestockDetailStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new ApiError(404, "x"));
    await s.load("m1"); expect(s.entries["m1"]).toBe("missing");
    vi.mocked(apiGet).mockRejectedValueOnce(new ApiError(500, "boom"));
    await s.load("e1"); expect(s.entries["e1"]).toBe("error"); expect(s.cache["e1"]).toBeUndefined();
    vi.mocked(apiGet).mockResolvedValueOnce({ ok: true, detail: detail("e1") } as any);
    await s.load("e1"); expect(s.entries["e1"]).toBe("ready"); // 重开可重试
    vi.mocked(apiGet).mockRejectedValueOnce(new UnauthenticatedError("401"));
    await s.load("u1"); expect(s.errorMsg["u1"]).toBeUndefined(); // 401 不写业务错
  });
});
```

- [ ] **Step 2: 运行确认失败 → Step 3 实现**

```ts
// frontend/src/stores/restockDetail.ts
import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, ApiError, UnauthenticatedError } from "../api/client";
import type { RestockDetail, RestockDetailResponse } from "../api/types.gen";

type Entry = "loading" | "ready" | "missing" | "error";

// 闭包级【非响应式】合并表——Promise 不进 reactive state
const inflight = new Map<string, Promise<void>>();

export const useRestockDetailStore = defineStore("restockDetail", () => {
  const entries = ref<Record<string, Entry>>({});
  const cache = ref<Record<string, RestockDetail>>({});
  const errorMsg = ref<Record<string, string>>({});

  function load(bc: string): Promise<void> {
    if (cache.value[bc]) { entries.value[bc] = "ready"; return Promise.resolve(); }
    if (inflight.has(bc)) return inflight.get(bc)!;
    entries.value[bc] = "loading";
    const p = (async () => {
      try {
        const data = await apiGet<RestockDetailResponse>(`/api/restock/${encodeURIComponent(bc)}/detail`);
        cache.value[bc] = data.detail;
        entries.value[bc] = "ready";
      } catch (e) {
        if (e instanceof UnauthenticatedError) return; // 401 中性，apiGet 已跳登录
        if (e instanceof ApiError && e.status === 404) { entries.value[bc] = "missing"; return; }
        entries.value[bc] = "error";
        errorMsg.value[bc] = (e as Error).message; // 500/网络：不写 cache，重开可重试
      } finally {
        inflight.delete(bc);
      }
    })();
    inflight.set(bc, p);
    return p;
  }

  return { entries, cache, errorMsg, load };
});
```

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/stores/restockDetail.test.ts
cd .. && git add frontend/src/stores/restockDetail.* && git commit -m "feat(restock-ui): restockDetail keyed store（按 bc 分区缓存 + inflight 合并 + A/B 隔离）"
```

---

## 阶段 D：drawer 组件 + 表格/页面接线

### Task 7: RestockDrawer.vue

**Files:**
- Create: `frontend/src/pages/restock/RestockDrawer.vue` + `.test.ts`
- Modify: `frontend/src/pages/restock/types.ts`

- [ ] **Step 1: types.ts re-export**

```ts
// frontend/src/pages/restock/types.ts — 追加
export type { RestockDetail } from "../../api/types.gen";
```

- [ ] **Step 2: 写组件测试（5 段 + 无操作按钮 + 三态 + 销售概况无 ×26）**

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
vi.mock("../../stores/restockDetail", () => {
  const state: any = { entries: {}, cache: {}, errorMsg: {}, load: vi.fn() };
  return { useRestockDetailStore: () => state, __state: state };
});
import { mount } from "@vue/test-utils";
import RestockDrawer from "./RestockDrawer.vue";
import { __state } from "../../stores/restockDetail";

const detail = () => ({
  barcode: "b1", master_sale_price_eur: 6, sale_net_avg: 5.8, retail_price_observed: 5.5,
  retail_price_estimate: 6.2, last_purchase_unit_price: 3, master_stock_price_eur: 3.2,
  margin_source: "purchase", margin_pct: 35, qty_total: 100, inventory_sale_value_eur: 600,
  inventory_cost_value_eur: 320, weeks_of_cover: 2, realized_profit_eur: 500,
  lifetime_invested_eur: 320, lifetime_purchase_qty: 60, lifetime_sale_revenue_eur: 800,
  lifetime_sale_qty: 70, net_cashflow_eur: 480, inventory_imbalance_pct: 12,
  is_history_truncated: false, first_event_at: "2021-07-01", total_qty: 700,
  n_active_weeks_26w: 18, weekly_velocity: 12.5, weekly_revenue: 80, retail_qty_26w: 3,
  retail_revenue_26w: 16.5, retail_share_26w: 0.04, urgency_score: 88.5,
  urgency_breakdown: { velocity: 25, cover: 28, recency: 8, margin: 22, demand_validity: 0.75, velocity_pctile: 0.83, margin_pctile: 0.61 },
});

beforeEach(() => {
  setActivePinia(createPinia());
  __state.entries = {}; __state.cache = {}; __state.errorMsg = {}; __state.load = vi.fn();
});

describe("RestockDrawer", () => {
  it("ready 渲染 5 段 + 无操作按钮", () => {
    __state.entries["b1"] = "ready"; __state.cache["b1"] = detail();
    const w = mount(RestockDrawer, { props: { barcode: "b1" } });
    expect(w.findAll(".rs-drawer-sec").length).toBe(5);
    expect(w.find(".rs-drawer-actions").exists()).toBe(false); // 操作按钮 Phase 3
  });
  it("销售概况：累计批发 + per-week，不出现 ×26 外推", () => {
    __state.entries["b1"] = "ready"; __state.cache["b1"] = detail();
    const w = mount(RestockDrawer, { props: { barcode: "b1" } });
    const txt = w.text();
    expect(txt).toContain("累计批发");
    expect(txt).not.toContain("×26");
    expect(txt).not.toContain("×26");
  });
  it("missing/error/loading 三态占位", () => {
    __state.entries["b1"] = "missing";
    let w = mount(RestockDrawer, { props: { barcode: "b1" } });
    expect(w.text()).toContain("无补货明细");
    __state.entries["b2"] = "error"; __state.errorMsg["b2"] = "boom";
    w = mount(RestockDrawer, { props: { barcode: "b2" } });
    expect(w.text()).toContain("明细加载失败");
    __state.entries["b3"] = "loading";
    w = mount(RestockDrawer, { props: { barcode: "b3" } });
    expect(w.text()).toContain("加载中");
  });
  it("onMounted 触发 load(barcode) 一次", () => {
    mount(RestockDrawer, { props: { barcode: "b9" } });
    expect(__state.load).toHaveBeenCalledTimes(1);
    expect(__state.load).toHaveBeenCalledWith("b9");
  });
});
```

- [ ] **Step 3: 运行确认失败 → 实现 RestockDrawer.vue**

实现要点：`onMounted(() => store.load(props.barcode))` 单触发；按 `store.entries[barcode]` 渲染 loading/missing/error/ready；ready 时读 `store.cache[barcode]` 渲染 5 段（移植 renderDrawer 只读，**去操作按钮**，销售概况用 §4 口径文案：「累计批发 {total_qty} 件」「周销速 {weekly_velocity} 件/周 · 周销额 €{weekly_revenue}/周」「真实零售 26 周 {retail_qty_26w} 件 / €{retail_revenue_26w}」，**不写 ×26**）。drawer-cells.ts 提供 profitStatus/retailPriceLine/cashflowImbalance/scoreSegments。scoped CSS 移植 `.rs-drawer*`/`.rs-drawer-sec`/`.rs-score-*`（components.css 1813-1845，token 变量，不全局 import）。

```vue
<!-- 骨架（完整段落实现时移植 renderDrawer 文案，去操作按钮） -->
<script setup lang="ts">
import { computed, onMounted } from "vue";
import { fmt, fmtEurOrDash } from "./cells"; // fmtEurOrDash 若无则在 cells.ts 加（见下注）
import { profitStatus, retailPriceLine, cashflowImbalance, scoreSegments } from "./drawer-cells";
import { useRestockDetailStore } from "../../stores/restockDetail";

const props = defineProps<{ barcode: string }>();
const store = useRestockDetailStore();
const state = computed(() => store.entries[props.barcode]);
const d = computed(() => store.cache[props.barcode]);
onMounted(() => store.load(props.barcode));
</script>

<template>
  <div class="rs-drawer">
    <p v-if="state === 'loading'" class="rs-drawer-muted">加载中…</p>
    <p v-else-if="state === 'missing'" class="rs-drawer-muted">无补货明细（该 SKU 不在汇总）</p>
    <p v-else-if="state === 'error'" class="rs-drawer-muted">明细加载失败：{{ store.errorMsg[props.barcode] }}（点行重开重试）</p>
    <div v-else-if="state === 'ready' && d" class="rs-drawer-grid">
      <!-- 5 个 <section class="rs-drawer-sec"> ... 财务/库存/盈亏/销售概况/紧迫分四维 -->
    </div>
  </div>
</template>
```

> `fmtEurOrDash(v)`：cells.ts 若无则加 `export const fmtEurOrDash = (v) => v == null ? "—" : "€" + fmt(v, 2)`（移植 restock.js:408），配单测。

- [ ] **Step 4: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/RestockDrawer.test.ts
cd .. && git add frontend/src/pages/restock/RestockDrawer.* frontend/src/pages/restock/types.ts frontend/src/pages/restock/cells.* && git commit -m "feat(restock-ui): RestockDrawer 5 段只读（销售概况准确口径 + 三态）"
```

---

### Task 8: RestockTable 行展开（click + keydown.self + 子按钮 stop）

**Files:**
- Modify: `frontend/src/pages/restock/RestockTable.vue` + `.test.ts`

- [ ] **Step 1: 写测试（展开单行/colspan/红队 click+keydown 不冒泡）**

```ts
// RestockTable.test.ts — 追加（rows 夹具已存在）
it("点行非按钮区 emit toggle-expand", async () => {
  const w = mount(RestockTable, { props: { rows: rows(2), coverThreshold: 4, sort: { key: "urgency_score", dir: "desc" } } });
  await w.findAll("tr.rs-row")[0].find(".rs-model").trigger("click");
  expect(w.emitted("toggle-expand")?.[0]).toEqual(["b0"]);
});
it("命中 expandedBarcode 插 drawer 行（colspan=14，单行）", () => {
  const w = mount(RestockTable, { props: { rows: rows(3), coverThreshold: 4, sort: { key: "urgency_score", dir: "desc" }, expandedBarcode: "b1" } });
  const drawerRows = w.findAll("tr.rs-drawer-row");
  expect(drawerRows.length).toBe(1);
  expect(drawerRows[0].find("td").attributes("colspan")).toBe("14");
  expect(w.find('tr.rs-row[aria-expanded="true"]').exists()).toBe(true);
});
it("红队 click：点货号/供应商不 emit toggle-expand", async () => {
  const w = mount(RestockTable, { props: { rows: rows(1), coverThreshold: 4, sort: { key: "urgency_score", dir: "desc" } } });
  await w.find(".rs-bc-link").trigger("click");
  await w.find(".rs-supplier").trigger("click");
  expect(w.emitted("toggle-expand")).toBeUndefined();
});
it("红队 keydown：聚焦货号/供应商按 Enter 不展开（.self）；聚焦行 Enter 展开", async () => {
  const w = mount(RestockTable, { props: { rows: rows(1), coverThreshold: 4, sort: { key: "urgency_score", dir: "desc" } } });
  await w.find(".rs-bc-link").trigger("keydown", { key: "Enter" });
  expect(w.emitted("toggle-expand")).toBeUndefined(); // 子按钮聚焦，.self 不触发
  await w.find("tr.rs-row").trigger("keydown.enter"); // 行自身（@vue/test-utils 模拟 target=currentTarget）
  expect(w.emitted("toggle-expand")?.[0]).toEqual(["b0"]);
});
```

> `@vue/test-utils` 触发 `tr.trigger("keydown.enter")` 时 `target===currentTarget`（tr 自身），`.self` 放行；`.rs-bc-link.trigger("keydown")` 时 target=按钮，冒泡到 tr 的 `.self` 拦下。

- [ ] **Step 2: 运行确认失败 → 实现**

RestockTable 改动：
- `defineProps` 加 `expandedBarcode?: string | null`；`defineEmits` 加 `(e: "toggle-expand", bc: string): void`。
- `<tr class="rs-row">` 加 `tabindex="0"`、`:aria-expanded="it.barcode === expandedBarcode"`、`@click="emit('toggle-expand', it.barcode)"`、`@keydown.enter.self.prevent="emit('toggle-expand', it.barcode)"`、`@keydown.space.self.prevent="emit('toggle-expand', it.barcode)"`、`style="cursor:pointer"`（或 CSS）。
- `rs-bc-link` 按钮：`@click` → `@click.stop`。`rs-supplier` 按钮：`@click` → `@click.stop`。
- 在 `<tr class="rs-row">` 之后（v-for 内）条件插：
```vue
<tr v-if="it.barcode === expandedBarcode" class="rs-drawer-row" :key="it.barcode + '__d'">
  <td colspan="14"><RestockDrawer :barcode="it.barcode" /></td>
</tr>
```
- `import RestockDrawer from "./RestockDrawer.vue";`
- scoped CSS：`.rs-drawer-row td { padding: 0; background: var(--bg-0); border-bottom: 1px solid var(--line-soft); }`；`.rs-row { cursor: pointer; }`。

> v-for 内插两个兄弟 `<tr>` 需用 `<template v-for>` 包裹或确保 key 唯一（行 key=barcode，drawer 行 key=barcode+'__d'）。改 `<template v-for="it in visible" :key="it.barcode">` 包 `<tr class="rs-row">` + 条件 `<tr class="rs-drawer-row">`。

- [ ] **Step 3: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/RestockTable.test.ts
cd .. && git add frontend/src/pages/restock/RestockTable.* && git commit -m "feat(restock-ui): RestockTable 行内联展开 drawer（click + keydown.self + 子按钮 stop）"
```

---

### Task 9: RestockPage expandedBarcode 编排

**Files:**
- Modify: `frontend/src/pages/restock/RestockPage.vue` + `.test.ts`

- [ ] **Step 1: 写集成测试（展开/切换/收起）**

```ts
// RestockPage.test.ts — 追加（apiGet mock 已在文件顶部）
it("点行展开 drawer 行；再点收起；点别行切换", async () => {
  vi.mocked(apiGet).mockImplementation(async (path: string) => {
    if (path === "/api/restock/items") return { ok: true, total: 2, items: [item({ barcode: "x" }), item({ barcode: "y" })] } as any;
    if (path.includes("/detail")) return { ok: true, detail: { barcode: path.includes("/x/") ? "x" : "y", urgency_breakdown: null } } as any;
    return { ok: true, items: {} } as any;
  });
  const w = mount(RestockPage);
  await flushPromises();
  await w.findAll("tr.rs-row")[0].trigger("click");
  await flushPromises();
  expect(w.findAll("tr.rs-drawer-row").length).toBe(1);
  await w.findAll("tr.rs-row")[0].trigger("click"); // 同行收起
  await flushPromises();
  expect(w.findAll("tr.rs-drawer-row").length).toBe(0);
});
```

> `item` 工厂已在 RestockPage.test.ts；确保它接受 `barcode` override（当前 `barcode: "b"+Math.random()`，加 `...p` 覆盖即可——已支持）。

- [ ] **Step 2: 运行确认失败 → 实现**

RestockPage 改动：
- `import { ref, shallowRef, ... }` 已有；加 `const expandedBarcode = shallowRef<string | null>(null);`
- `function onToggleExpand(bc: string) { expandedBarcode.value = expandedBarcode.value === bc ? null : bc; }`
- 加载/筛选/排序变化时收起：在 `onUpdateFilter`/`onSortChange`/`onSelectSupplier` 末尾置 `expandedBarcode.value = null`（避免展开行被筛掉后残留）。
- 模板 `<RestockTable ... :expanded-barcode="expandedBarcode" @toggle-expand="onToggleExpand" />`

- [ ] **Step 3: 通过 + Commit**

```bash
cd frontend && npx vitest run src/pages/restock/RestockPage.test.ts
cd .. && git add frontend/src/pages/restock/RestockPage.* && git commit -m "feat(restock-ui): RestockPage expandedBarcode 编排（切换/收起/筛排变化收起）"
```

---

## 阶段 E：e2e + 回归

### Task 10: e2e smoke 扩展（点行 → drawer 现）

**Files:**
- Modify: `e2e/test_restock_smoke.py`

- [ ] **Step 1: 追加 smoke**

```python
# e2e/test_restock_smoke.py — 追加（seed_restock fixture 已存在，payload 已含 drawer 字段）
@pytest.mark.smoke
@requires_dist
def test_restock_drawer_expands(seed_restock, page_with_console):
    page = page_with_console
    page.goto(f"{seed_restock}/ui/restock")
    page.wait_for_selector("tr.rs-row", timeout=10000)
    page.locator("tr.rs-row").first.click()
    page.wait_for_selector("tr.rs-drawer-row", timeout=10000)
    assert page.locator(".rs-drawer-sec").count() >= 1
    assert page.console_errors == [], f"console errors: {page.console_errors}"
```

> `seed_restock` 的 `_payload()` 需含 drawer 字段（lifetime_*/urgency_breakdown 等）。Task 10 Step 2 先核对：若缺则补全 `_payload()`（喂满 RestockDetail 白名单 + 10 键 breakdown），使 `/detail` 投影通过。

- [ ] **Step 2: 补 `_payload()` drawer 字段 + 运行**

Run: `cd frontend && npm run build && cd .. && python -m pytest e2e/test_restock_smoke.py -v`
Expected: PASS（2 个 smoke）

- [ ] **Step 3: Commit**

```bash
git add e2e/test_restock_smoke.py
git commit -m "test(e2e): /ui/restock 点行展开 drawer smoke"
```

---

### Task 11: 全量回归 + 收尾

- [ ] **Step 1: 后端全测 + ruff**

Run: `python -m pytest tests/ -q && python -m ruff check .`
Expected: 全绿 + ruff All checks passed

- [ ] **Step 2: 前端 test:unit + vue-tsc + build**

Run: `cd frontend && npm run test:unit && npx vue-tsc --noEmit && npm run build`
Expected: 全绿；vue-tsc 0；build 成功

- [ ] **Step 3: gen_ts_types 漂移**

Run: `python tools/gen_ts_types.py --check`
Expected: 退出码 0

- [ ] **Step 4: no-analytics guard 复查**

Run: `cd frontend && npx vitest run src/pages/restock/no-analytics.test.ts`
Expected: PASS（drawer/store 只走 `/api/restock/*`）

- [ ] **Step 5: 浏览器验收（本地双栈）**

`./dev.ps1 -Frontend` → `http://localhost:5173/ui/restock` 点行展开，对照旧页 drawer：5 段内容一致、销售概况口径准确（无 ×26）、点货号/供应商不展开、Enter/Space 行为正确、缺成本/停用 SKU 三态占位。

- [ ] **Step 6: PR**

```bash
git push -u origin feat/restock-vue-phase2
# gh pr create，描述贴：drawer 5 段 1:1 + 销售概况口径修正 + keyed store A/B 隔离 + 键盘红队
```
> push 前确认非周一 14:00 scraper 窗口；本地已浏览器验收。

---

## Self-Review（对照 spec）

- §2 API（detail 端点 + compute_restock_snapshot + 显式嵌套投影 + 404）→ Task 1-3 ✅
- §2 schema（独立 breakdown + 收紧 nullability）→ Task 1 ✅
- §4 销售概况口径（累计批发/per-week/真实零售/无外推）→ Task 5/7 ✅
- §5 keyed store（cache/inflight 闭包 Map/A-B 隔离/404·500·401 分流）→ Task 6 ✅
- §5 ApiError status → Task 4 ✅
- §3/§5 行展开（click + keydown.self + 子按钮 stop + aria-expanded + 单行 colspan=14）→ Task 8 ✅
- §3 drawer 5 段只读无操作按钮 + 三态 → Task 7 ✅
- §6 测试（10 键投影丢 3 / 子字段非空拒 None / 404 精确 / 结构性 mock / 键盘红队 / A-B 隔离）→ Task 1/2/6/8 ✅
- §6 e2e → Task 10 ✅
- §7 items 端点冻结 → 全程不碰 `_project_item`/RestockItem ✅
