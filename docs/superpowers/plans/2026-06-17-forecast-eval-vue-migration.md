# 预测效果页（forecast_eval）迁移 Vue 独立栈 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「预测效果」页（旧 SPA `?page=forecast_eval`）忠实 1:1 迁移到 Vue 独立栈 `/ui/forecast-eval`，作为简报之后第二个范式页，跑通 pydantic schema → TS 类型 → vue-router → vitest 烟雾的完整迁移流水线。

**Architecture:** 复刻简报迁移那套（已上线 #63/#69）：新增 canonical `GET /api/forecast-eval/data`（pydantic 校验，schema 漂移即 500）→ `gen_ts_types.py` 同步 TS 类型 → 前端 `normalize`（API 边界唯一收窄点）+ pinia store + Vue 组件 → vue-router 注册 + `nav-items.ts` 翻 `legacyPageId`→`routeName` → 退役旧 SPA 标签。纯只读，不碰数据。

**Tech Stack:** Flask + pydantic（后端契约）、Vue 3 `<script setup>` + pinia + vue-router + vitest（前端）、pytest（后端）。

**关键事实（已核实，勿重新假设）：**
- 旧实现真相：`static/js/forecast_eval.js`（125 行，单 `GET /analytics/backtest/dashboard`，纯只读，无 SVG，tier 条是 CSS 宽度）。**docs/design 无 forecast_eval 重排红稿（红稿 01-09 的 09 是「系统管理」）→ 做忠实移植，不掺重排。**
- 后端聚合逻辑已存在：`app/services/forecast_eval.py::build_forecast_eval_dashboard(session)`，返回 `{run_id, backtest_date, forecast_skus, scored_skus, tiers, headline, by_sku_type, models}`。空库返回合法空形状（run_id=None, tiers 全 0, headline.n=0 其余 None, 列表空）。
- `backtest_date` 与 `models[].created_at` 来自 `BacktestRun.created_at`，列类型 `Mapped[str | None]`（Text）→ **schema 用 `str | None`**。
- 简报范式参照文件：`app/routes/briefing.py`（api_bp）、`app/schemas_api.py`、`tools/gen_ts_types.py`、`frontend/src/stores/briefing.ts`、`frontend/src/pages/briefing/{normalize,types,BriefingPage}.ts/vue`、`frontend/src/router.ts`、`frontend/src/shell/nav-items.ts`。
- 测试夹具：`tests/test_api_me.py` 的 `client` fixture = `create_app(seed_auth=False, prewarm=False).test_client()`；seed 走 SQLAlchemy `insert()`（见 `tests/test_forecast_eval_dashboard.py`）。前端测试 `cd frontend && npm run test`（vitest run）。
- 旧 SPA 是单体 `templates/index.html`（`?page=forecast_eval` 客户端切换，无独立 Flask 路由）；forecast_eval 不在 `e2e/test_smoke_nav.py` 的 `_NAV_PAGES` 里（无旧烟雾要删）。

---

## 文件结构

**后端：**
- 修改 `app/schemas_api.py` — 新增 `ForecastEvalData` 及嵌套模型 + 加入 `API_MODELS`
- 创建 `app/routes/forecast_eval.py` — `api_bp`（`/api/forecast-eval/data`），职责单一：调 service + pydantic 校验后 jsonify
- 修改 `app/routes/__init__.py` — 注册新蓝图
- 创建 `tests/test_forecast_eval_api.py` — 端点契约测试（空库 + seeded）

**类型生成（自动产物）：**
- 修改 `frontend/src/api/types.gen.ts` — `python tools/gen_ts_types.py` 重新生成，勿手改

**前端：**
- 创建 `frontend/src/pages/forecast-eval/types.ts` — 视图模型（VM）类型
- 创建 `frontend/src/pages/forecast-eval/normalize.ts` + `normalize.test.ts` — API 边界唯一收窄点
- 创建 `frontend/src/stores/forecastEval.ts` + `forecastEval.test.ts` — pinia store
- 创建 `frontend/src/pages/forecast-eval/ForecastEvalPage.vue` + `ForecastEvalPage.test.ts` — 页面组件
- 修改 `frontend/src/router.ts` — 注册 `forecast-eval` 路由
- 修改 `frontend/src/shell/nav-items.ts` — `forecast_eval` 翻 `routeName`
- 修改 `frontend/src/shell/SidebarNav.test.ts` — 断言 forecast-eval=RouterLink（真正覆盖 RouterLink/legacy href 的测试在此，非 nav-items.test.ts）

**旧页退役：**
- 修改 `static/js/store.js` — 从 `Alpine.store("nav").pages` 数组删 forecast_eval（侧栏入口真实源）
- 修改 `templates/index.html` — 删 `#pageForecastEval` div + `forecast_eval.js` script include
- 删除 `static/js/forecast_eval.js`

---

## Task 1: 后端 pydantic schema + canonical 端点 + 注册 + 测试

**Files:**
- Modify: `app/schemas_api.py`
- Create: `app/routes/forecast_eval.py`
- Modify: `app/routes/__init__.py`
- Test: `tests/test_forecast_eval_api.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_forecast_eval_api.py`。

> **鉴权范式（已核实）**：全局 auth（`app/auth.py:128-131`）对未登录 `/api/*` 返回 JSON 401，故 fixture 不能裸 GET 期望 200。本仓库 `/api/*` 数据端点的 canonical 测试写法 = 带 `X-Upload-Token`（见 `tests/test_api_briefing.py`，token 通过 `app/auth.py:116-117` 放行任意端点）。**直接镜像该范式。**
>
> **seed 字段（已核实）**：`ForecastOutput`/`BacktestResult` 有多个 NOT NULL 列（`model_used`/`mu`/`sigma`/`p50`/`p98`；`n_weeks_train`/`n_weeks_test`/`bias`/`mean_actual`/`mean_predicted`）。下方 seed helper **逐字复制自 `tests/test_forecast_eval_dashboard.py:30-79`**，已填全。

```python
"""GET /api/forecast-eval/data：预测效果看板 canonical 端点（pydantic 契约）。

参照 app/services/forecast_eval.build_forecast_eval_dashboard 的形状。纯只读。
鉴权镜像 tests/test_api_briefing.py（X-Upload-Token）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from app.models import BacktestResult, BacktestRun, ForecastOutput, Stockpile
from app.repositories import stockpile_db


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def _get(app):
    return app.test_client().get(
        "/api/forecast-eval/data", headers={"X-Upload-Token": "test-token-123"}
    )


# ---- seed helpers（复制自 tests/test_forecast_eval_dashboard.py，含全部 NOT NULL 列）----
def _seed_run(model="EmpiricalQuantile", view="base_demand") -> int:
    with stockpile_db._session() as s:
        res = s.execute(
            insert(BacktestRun).values(
                model_name=model, view=view, window_train=13, window_test=4,
                min_weeks=20, n_skus_total=0, n_skus_scored=0,
            )
        )
        s.commit()
        return res.inserted_primary_key[0]


def _seed_forecast(barcode, *, hist, nz, zero8, stockout_zero8=0, sku_type="retail_dominant"):
    with stockpile_db._session() as s:
        s.execute(insert(Stockpile).values(
            product_barcode=barcode, product_model=barcode, stockpile_location="", is_active=1,
        ))
        s.execute(insert(ForecastOutput).values(
            product_barcode=barcode, model_used="EmpiricalQuantile", sku_type=sku_type,
            n_weeks_history=hist, nonzero_weeks=nz, zero_weeks_last8=zero8,
            stockout_zero_weeks_last8=stockout_zero8,
            mu=1.0, sigma=1.0, p50=1.0, p98=3.0,
        ))
        s.commit()


def _seed_result(run_id, barcode, *, mase, cov, sku_type="retail_dominant"):
    with stockpile_db._session() as s:
        s.execute(insert(BacktestResult).values(
            run_id=run_id, product_barcode=barcode, sku_type=sku_type,
            n_weeks_train=52, n_weeks_test=4, mape=0.2, mase=mase, bias=0.0,
            coverage_p98=cov, mean_actual=5.0, mean_predicted=5.0,
        ))
        s.commit()


def test_forecast_eval_unauthenticated_returns_json_401(real_app):
    """未带 token / 未登录：/api/* 必须 JSON 401（不渲染 200，不跳 HTML 登录页）。"""
    r = real_app.test_client().get("/api/forecast-eval/data")
    assert r.status_code == 401
    assert r.get_json() == {"error": "unauthenticated"}


def test_forecast_eval_empty_db_returns_valid_empty_shape(real_app):
    """空库（仅 seed_auth，无 forecast 数据）：200 + run_id None + tiers 全 0 + 列表空。"""
    r = _get(real_app)
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["run_id"] is None
    assert body["forecast_skus"] == 0
    assert body["scored_skus"] == 0
    assert body["tiers"] == {"high": 0, "medium": 0, "low": 0}
    assert body["headline"]["n"] == 0
    assert body["by_sku_type"] == []
    assert body["models"] == []


def test_forecast_eval_seeded_returns_run_and_tiers(real_app):
    """seed 生产 run + 一条已评分高可信 SKU：run_id 出现，high tier 计数 1，模型列表含生产模型。"""
    run_id = _seed_run()
    _seed_forecast("B1", hist=60, nz=20, zero8=0)
    _seed_result(run_id, "B1", mase=0.5, cov=0.99)

    r = _get(real_app)
    assert r.status_code == 200
    body = r.get_json()
    assert body["run_id"] == run_id
    assert body["forecast_skus"] == 1
    assert body["scored_skus"] == 1
    assert body["tiers"]["high"] == 1
    assert body["headline"]["beats_naive_pct"] == 100.0
    assert any(m["model_name"] == "EmpiricalQuantile" and m["is_production"] for m in body["models"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_forecast_eval_api.py -v`
Expected: 401 测试已 PASS（auth 已生效）；两个 token 测试 FAIL（端点 404 / `ForecastEvalData` 未定义）。

- [ ] **Step 3: 加 pydantic schema**

在 `app/schemas_api.py`，`MeData` 之后、`API_MODELS` 之前插入：

```python
class ForecastEvalMetrics(BaseModel):
    """headline / by_sku_type / models 共享的聚合指标块（_aggregate_metrics 输出）。"""

    model_config = ConfigDict(extra="forbid")

    n: int
    median_mase: float | None
    beats_naive_pct: float | None
    avg_coverage_p98: float | None


class ForecastEvalByType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_type: str
    n: int
    median_mase: float | None
    beats_naive_pct: float | None
    avg_coverage_p98: float | None


class ForecastEvalModelRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str
    run_id: int
    created_at: str | None
    is_production: bool
    n: int
    median_mase: float | None
    beats_naive_pct: float | None
    avg_coverage_p98: float | None


class ForecastEvalTiers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high: int
    medium: int
    low: int


class ForecastEvalData(BaseModel):
    """GET /api/forecast-eval/data 响应。形状对齐
    forecast_eval.build_forecast_eval_dashboard + 路由加的 ok。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    run_id: int | None
    backtest_date: str | None
    forecast_skus: int
    scored_skus: int
    tiers: ForecastEvalTiers
    headline: ForecastEvalMetrics
    by_sku_type: list[ForecastEvalByType]
    models: list[ForecastEvalModelRow]
```

并把 `API_MODELS` 行改为（保持已有顺序，追加新模型）：

```python
API_MODELS: list[type[BaseModel]] = [BriefingData, MeData, ForecastEvalData]
```

> 注：`ForecastEvalMetrics` 不直接进 `API_MODELS`（只作 `headline` 字段类型被 `$ref`），`gen_ts_types` 会从 `$defs` 自动带出它的 interface。

- [ ] **Step 4: 建路由文件**

创建 `app/routes/forecast_eval.py`：

```python
"""预测效果看板 canonical 端点（前端独立化 §11，2026-06-17 迁 Vue）。

只读，走 session auth。聚合逻辑在 services/forecast_eval；本端点是 §6 的
pydantic 契约出口——schema 与现实漂移即 500（与 /api/briefing/data 同纪律）。
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app.repositories import stockpile_db
from app.services.forecast_eval import build_forecast_eval_dashboard

api_bp = Blueprint("api_forecast_eval", __name__, url_prefix="/api/forecast-eval")


@api_bp.get("/data")
def data():
    from app.schemas_api import ForecastEvalData

    with stockpile_db._session() as session:
        payload = {"ok": True, **build_forecast_eval_dashboard(session)}
    return jsonify(ForecastEvalData.model_validate(payload).model_dump())
```

- [ ] **Step 5: 注册蓝图**

在 `app/routes/__init__.py`：import 区加（按字母序，紧跟 briefing import 之后即可）

```python
from app.routes.forecast_eval import api_bp as forecast_eval_api_bp
```

`register_routes` 体内、`app.register_blueprint(analytics_bp)` 之后加：

```python
    app.register_blueprint(forecast_eval_api_bp)
```

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest tests/test_forecast_eval_api.py -v`
Expected: PASS（3 个测试：401 契约 + 空库 + seeded）

- [ ] **Step 7: 提交**

```bash
git add app/schemas_api.py app/routes/forecast_eval.py app/routes/__init__.py tests/test_forecast_eval_api.py
git commit -m "feat(forecast-eval): canonical /api/forecast-eval/data + pydantic schema"
```

---

## Task 2: 重新生成 TS 类型

**Files:**
- Modify: `frontend/src/api/types.gen.ts`（自动产物，勿手改）

- [ ] **Step 1: 生成**

Run: `python tools/gen_ts_types.py`
Expected: 输出 `wrote .../frontend/src/api/types.gen.ts`

- [ ] **Step 2: 验证漂移检查通过**

Run: `python tools/gen_ts_types.py --check`
Expected: 退出码 0（无输出）。`git diff frontend/src/api/types.gen.ts` 应能看到新增 `ForecastEvalMetrics` / `ForecastEvalByType` / `ForecastEvalModelRow` / `ForecastEvalTiers` / `ForecastEvalData` interface。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/types.gen.ts
git commit -m "chore(forecast-eval): 同步 TS 类型 (gen_ts_types)"
```

---

## Task 3: 前端 VM 类型 + normalize（API 边界收窄）

**Files:**
- Create: `frontend/src/pages/forecast-eval/types.ts`
- Create: `frontend/src/pages/forecast-eval/normalize.ts`
- Test: `frontend/src/pages/forecast-eval/normalize.test.ts`

- [ ] **Step 1: 写 VM 类型**

创建 `frontend/src/pages/forecast-eval/types.ts`：

```typescript
export interface MetricsVM {
  n: number;
  medianMase: number | null;
  beatsNaivePct: number | null;
  avgCoverageP98: number | null;
}
export interface ByTypeRow extends MetricsVM {
  skuType: string;
}
export interface ModelRow extends MetricsVM {
  modelName: string;
  runId: number;
  createdAt: string | null;
  isProduction: boolean;
}
export interface ForecastEvalViewModel {
  missing: boolean; // run_id == null：尚无回测数据
  runId: number | null;
  backtestDate: string | null;
  forecastSkus: number;
  scoredSkus: number;
  tiers: { high: number; medium: number; low: number };
  headline: MetricsVM;
  byType: ByTypeRow[];
  models: ModelRow[];
}
```

- [ ] **Step 2: 写失败测试**

创建 `frontend/src/pages/forecast-eval/normalize.test.ts`：

```typescript
import { describe, expect, it } from "vitest";
import type { ForecastEvalData } from "../../api/types.gen";
import { normalizeForecastEval } from "./normalize";

const EMPTY: ForecastEvalData = {
  ok: true, run_id: null, backtest_date: null, forecast_skus: 0, scored_skus: 0,
  tiers: { high: 0, medium: 0, low: 0 },
  headline: { n: 0, median_mase: null, beats_naive_pct: null, avg_coverage_p98: null },
  by_sku_type: [], models: [],
};

describe("normalizeForecastEval", () => {
  it("空数据 → missing=true，计数归零", () => {
    const vm = normalizeForecastEval(EMPTY);
    expect(vm.missing).toBe(true);
    expect(vm.tiers).toEqual({ high: 0, medium: 0, low: 0 });
    expect(vm.byType).toEqual([]);
    expect(vm.models).toEqual([]);
  });

  it("有 run → missing=false，字段转 camelCase", () => {
    const vm = normalizeForecastEval({
      ...EMPTY,
      run_id: 44,
      backtest_date: "2026-06-15T01:00:00",
      forecast_skus: 100,
      scored_skus: 80,
      tiers: { high: 10, medium: 30, low: 60 },
      headline: { n: 80, median_mase: 0.83, beats_naive_pct: 62.5, avg_coverage_p98: 0.97 },
      by_sku_type: [
        { sku_type: "retail_dominant", n: 50, median_mase: 0.8, beats_naive_pct: 70, avg_coverage_p98: 0.98 },
      ],
      models: [
        { model_name: "EmpiricalQuantile", run_id: 44, created_at: "2026-06-15", is_production: true, n: 80, median_mase: 0.83, beats_naive_pct: 62.5, avg_coverage_p98: 0.97 },
      ],
    });
    expect(vm.missing).toBe(false);
    expect(vm.runId).toBe(44);
    expect(vm.headline.beatsNaivePct).toBe(62.5);
    expect(vm.byType[0].skuType).toBe("retail_dominant");
    expect(vm.models[0].isProduction).toBe(true);
  });
});
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/forecast-eval/normalize.test.ts`
Expected: FAIL（`normalizeForecastEval` 不存在）

- [ ] **Step 4: 写 normalize**

创建 `frontend/src/pages/forecast-eval/normalize.ts`：

```typescript
import type {
  ForecastEvalByType,
  ForecastEvalData,
  ForecastEvalMetrics,
  ForecastEvalModelRow,
} from "../../api/types.gen";
import type { ByTypeRow, ForecastEvalViewModel, MetricsVM, ModelRow } from "./types";

function num(x: unknown): number | null {
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}
function metrics(m: ForecastEvalMetrics): MetricsVM {
  return {
    n: num(m.n) ?? 0,
    medianMase: num(m.median_mase),
    beatsNaivePct: num(m.beats_naive_pct),
    avgCoverageP98: num(m.avg_coverage_p98),
  };
}

/** API 边界唯一收窄点：组件只吃 ForecastEvalViewModel，不碰 raw。 */
export function normalizeForecastEval(raw: ForecastEvalData): ForecastEvalViewModel {
  const byType: ByTypeRow[] = (raw.by_sku_type ?? []).map((r: ForecastEvalByType) => ({
    skuType: r.sku_type,
    ...metrics(r),
  }));
  const models: ModelRow[] = (raw.models ?? []).map((m: ForecastEvalModelRow) => ({
    modelName: m.model_name,
    runId: num(m.run_id) ?? 0,
    createdAt: m.created_at ?? null,
    isProduction: m.is_production === true,
    ...metrics(m),
  }));
  return {
    missing: raw.run_id == null,
    runId: num(raw.run_id),
    backtestDate: raw.backtest_date ?? null,
    forecastSkus: num(raw.forecast_skus) ?? 0,
    scoredSkus: num(raw.scored_skus) ?? 0,
    tiers: {
      high: num(raw.tiers?.high) ?? 0,
      medium: num(raw.tiers?.medium) ?? 0,
      low: num(raw.tiers?.low) ?? 0,
    },
    headline: metrics(raw.headline),
    byType,
    models,
  };
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/pages/forecast-eval/normalize.test.ts`
Expected: PASS（2 个测试）

- [ ] **Step 6: 提交**

```bash
git add frontend/src/pages/forecast-eval/types.ts frontend/src/pages/forecast-eval/normalize.ts frontend/src/pages/forecast-eval/normalize.test.ts
git commit -m "feat(forecast-eval): VM 类型 + normalize 收窄层"
```

---

## Task 4: 前端 pinia store

**Files:**
- Create: `frontend/src/stores/forecastEval.ts`
- Test: `frontend/src/stores/forecastEval.test.ts`

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/stores/forecastEval.test.ts`（镜像 `briefing.test.ts`）：

```typescript
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  UnauthenticatedError: class UnauthenticatedError extends Error {},
  apiGet: vi.fn(async () => ({
    ok: true, run_id: 44, backtest_date: "2026-06-15", forecast_skus: 100, scored_skus: 80,
    tiers: { high: 10, medium: 30, low: 60 },
    headline: { n: 80, median_mase: 0.83, beats_naive_pct: 62.5, avg_coverage_p98: 0.97 },
    by_sku_type: [], models: [],
  })),
}));

import { apiGet, UnauthenticatedError } from "../api/client";
import { useForecastEvalStore } from "./forecastEval";

describe("forecastEval store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("load 填充 vm 并清 loading", async () => {
    const s = useForecastEvalStore();
    const p = s.load();
    expect(s.loading).toBe(true);
    await p;
    expect(s.loading).toBe(false);
    expect(s.vm?.runId).toBe(44);
    expect(s.vm?.missing).toBe(false);
    expect(s.error).toBeNull();
  });

  it("load 失败 → error 填充，vm 保持 null", async () => {
    const s = useForecastEvalStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    await s.load();
    expect(s.error).toBe("boom");
    expect(s.vm).toBeNull();
  });

  it("未登录错误被吞掉，不污染 error", async () => {
    const s = useForecastEvalStore();
    vi.mocked(apiGet).mockRejectedValueOnce(new UnauthenticatedError("x"));
    await s.load();
    expect(s.error).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/stores/forecastEval.test.ts`
Expected: FAIL（`useForecastEvalStore` 不存在）

- [ ] **Step 3: 写 store**

创建 `frontend/src/stores/forecastEval.ts`（镜像 `briefing.ts`）：

```typescript
import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet, UnauthenticatedError } from "../api/client";
import type { ForecastEvalData } from "../api/types.gen";
import { normalizeForecastEval } from "../pages/forecast-eval/normalize";
import type { ForecastEvalViewModel } from "../pages/forecast-eval/types";

export const useForecastEvalStore = defineStore("forecastEval", () => {
  const vm = ref<ForecastEvalViewModel | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function load() {
    loading.value = true;
    error.value = null;
    try {
      const raw = await apiGet<ForecastEvalData>("/api/forecast-eval/data");
      vm.value = normalizeForecastEval(raw);
    } catch (e) {
      if (e instanceof UnauthenticatedError) return;
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  return { vm, loading, error, load };
});
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/stores/forecastEval.test.ts`
Expected: PASS（3 个测试）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/stores/forecastEval.ts frontend/src/stores/forecastEval.test.ts
git commit -m "feat(forecast-eval): pinia store"
```

---

## Task 5: 前端页面组件 ForecastEvalPage.vue

**Files:**
- Create: `frontend/src/pages/forecast-eval/ForecastEvalPage.vue`
- Test: `frontend/src/pages/forecast-eval/ForecastEvalPage.test.ts`

旧页结构（`forecast_eval.js` render）= 标题 + 新鲜度行 + 4 个 KPI（MASE<1 占比 / 中位 MASE / 覆盖@p98 / 评分/预测 SKU）+ 置信度分布条（high/medium/low CSS 宽度段 + 图例）+「按 SKU 类型」表 +「模型对比」表。忠实移植。

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/pages/forecast-eval/ForecastEvalPage.test.ts`。

> **范式（已核实）**：仓库既有组件测试 **不用真 pinia** —— `vi.mock` 掉 store 模块返回一个 plain `state` 对象，mount 前直接改 `state.vm/loading/error`（见 `frontend/src/pages/briefing/BriefingPage.test.ts:21`）。真 pinia 会触发真实 `onMounted().load()→apiGet`，污染组件单测。镜像 mock-store 写法。

```typescript
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { ForecastEvalViewModel } from "./types";

function vmStub(over: Partial<ForecastEvalViewModel> = {}): ForecastEvalViewModel {
  return {
    missing: false, runId: 44, backtestDate: "2026-06-15", forecastSkus: 100, scoredSkus: 80,
    tiers: { high: 10, medium: 30, low: 60 },
    headline: { n: 80, medianMase: 0.83, beatsNaivePct: 62.5, avgCoverageP98: 0.97 },
    byType: [{ skuType: "retail_dominant", n: 50, medianMase: 0.8, beatsNaivePct: 70, avgCoverageP98: 0.98 }],
    models: [{ modelName: "EmpiricalQuantile", runId: 44, createdAt: "2026-06-15", isProduction: true, n: 80, medianMase: 0.83, beatsNaivePct: 62.5, avgCoverageP98: 0.97 }],
    ...over,
  };
}

const state = { vm: null as ForecastEvalViewModel | null, loading: false, error: null as string | null, load: vi.fn() };
vi.mock("../../stores/forecastEval", () => ({ useForecastEvalStore: () => state }));

import ForecastEvalPage from "./ForecastEvalPage.vue";

describe("ForecastEvalPage", () => {
  it("loading 时显示加载中", () => {
    state.vm = null; state.loading = true; state.error = null;
    const w = mount(ForecastEvalPage);
    expect(w.text()).toContain("加载中");
  });

  it("missing 时显示空态提示", () => {
    state.loading = false; state.error = null;
    state.vm = vmStub({ missing: true, runId: null, backtestDate: null, forecastSkus: 0, scoredSkus: 0, tiers: { high: 0, medium: 0, low: 0 }, byType: [], models: [] });
    const w = mount(ForecastEvalPage);
    expect(w.text()).toContain("尚无回测数据");
  });

  it("有数据时渲染 KPI + tier 计数 + 模型行", () => {
    state.loading = false; state.error = null; state.vm = vmStub();
    const w = mount(ForecastEvalPage);
    expect(w.text()).toContain("63%"); // beatsNaivePct round
    expect(w.text()).toContain("retail_dominant");
    expect(w.text()).toContain("EmpiricalQuantile");
    expect(w.text()).toContain("60"); // tier low 计数
  });

  it("系统级 error → 整页错误态", () => {
    state.vm = null; state.loading = false; state.error = "API 500: /api/forecast-eval/data";
    const w = mount(ForecastEvalPage);
    expect(w.text()).toContain("API 500");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/forecast-eval/ForecastEvalPage.test.ts`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 写组件**

创建 `frontend/src/pages/forecast-eval/ForecastEvalPage.vue`：

```vue
<script setup lang="ts">
import { computed, onMounted } from "vue";
import PageHeader from "../../components/PageHeader.vue";
import { useForecastEvalStore } from "../../stores/forecastEval";

const store = useForecastEvalStore();
onMounted(() => store.load());
const vm = computed(() => store.vm);

const fmtMase = (v: number | null) => (v == null ? "—" : v.toFixed(2));
const fmtPct = (v: number | null) => (v == null ? "—" : `${Math.round(v)}%`);
const fmtCov = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);

const subtitle = computed(() => {
  const v = vm.value;
  if (!v || v.missing) return undefined;
  return `run #${v.runId} · ${v.backtestDate ?? "—"}`;
});

const tierTotal = computed(() => {
  const t = vm.value?.tiers;
  return t ? (t.high + t.medium + t.low) || 1 : 1;
});
const segPct = (n: number) => `${((n / tierTotal.value) * 100).toFixed(1)}%`;
</script>

<template>
  <main class="fe">
    <PageHeader title="预测效果" :subtitle="subtitle" />

    <p v-if="store.loading" class="fe__msg">加载中…</p>
    <p v-else-if="store.error" class="fe__error">{{ store.error }}</p>

    <template v-else-if="vm">
      <div v-if="vm.missing" class="fe__banner">
        尚无回测数据，置信度全部按缺失评为低。先触发一次 backtest 再来看。
      </div>

      <div class="fe__kpis">
        <div class="fe__kpi"><span class="fe__kpi-v">{{ fmtPct(vm.headline.beatsNaivePct) }}</span><span class="fe__kpi-l">MASE&lt;1 占比</span></div>
        <div class="fe__kpi"><span class="fe__kpi-v">{{ fmtMase(vm.headline.medianMase) }}</span><span class="fe__kpi-l">中位 MASE</span></div>
        <div class="fe__kpi"><span class="fe__kpi-v">{{ fmtCov(vm.headline.avgCoverageP98) }}</span><span class="fe__kpi-l">覆盖 @p98</span></div>
        <div class="fe__kpi"><span class="fe__kpi-v">{{ vm.scoredSkus }}/{{ vm.forecastSkus }}</span><span class="fe__kpi-l">评分 / 预测 SKU</span></div>
      </div>

      <div class="fe__tiers">
        <span class="fe__tiers-label">置信度分布</span>
        <div class="fe__bar">
          <div class="fe__seg fe__seg--high" :style="{ width: segPct(vm.tiers.high) }"></div>
          <div class="fe__seg fe__seg--medium" :style="{ width: segPct(vm.tiers.medium) }"></div>
          <div class="fe__seg fe__seg--low" :style="{ width: segPct(vm.tiers.low) }"></div>
        </div>
        <div class="fe__legend">
          <span><i class="fe__dot fe__dot--high"></i>高 {{ vm.tiers.high }}</span>
          <span><i class="fe__dot fe__dot--medium"></i>中 {{ vm.tiers.medium }}</span>
          <span><i class="fe__dot fe__dot--low"></i>低 {{ vm.tiers.low }}</span>
        </div>
      </div>

      <section class="fe__pnl">
        <div class="fe__pnl-hd">按 SKU 类型</div>
        <table class="fe__table">
          <thead><tr><th>SKU 类型</th><th class="fe__num">评分数</th><th class="fe__num">中位MASE</th><th class="fe__num">胜Naive%</th><th class="fe__num">覆盖</th></tr></thead>
          <tbody>
            <tr v-for="r in vm.byType" :key="r.skuType">
              <td>{{ r.skuType }}</td>
              <td class="fe__num">{{ r.n }}</td>
              <td class="fe__num">{{ fmtMase(r.medianMase) }}</td>
              <td class="fe__num">{{ fmtPct(r.beatsNaivePct) }}</td>
              <td class="fe__num">{{ fmtCov(r.avgCoverageP98) }}</td>
            </tr>
            <tr v-if="!vm.byType.length"><td colspan="5" class="fe__empty">—</td></tr>
          </tbody>
        </table>
      </section>

      <section class="fe__pnl">
        <div class="fe__pnl-hd">模型对比</div>
        <table class="fe__table">
          <thead><tr><th>模型</th><th class="fe__num">中位MASE</th><th class="fe__num">胜Naive%</th><th class="fe__num">覆盖</th><th>生产</th></tr></thead>
          <tbody>
            <tr v-for="m in vm.models" :key="m.modelName" :class="{ 'fe__row--prod': m.isProduction }">
              <td>{{ m.modelName }}</td>
              <td class="fe__num">{{ fmtMase(m.medianMase) }}</td>
              <td class="fe__num">{{ fmtPct(m.beatsNaivePct) }}</td>
              <td class="fe__num">{{ fmtCov(m.avgCoverageP98) }}</td>
              <td>{{ m.isProduction ? "★" : "" }}</td>
            </tr>
            <tr v-if="!vm.models.length"><td colspan="5" class="fe__empty">—</td></tr>
          </tbody>
        </table>
      </section>
    </template>
  </main>
</template>

<style scoped>
.fe { padding: var(--sp-6); max-width: 1200px; margin: 0 auto; }
.fe__msg { color: var(--ink-1); }
.fe__error { color: var(--error); }
.fe__banner {
  background: var(--warn-subtle); border: 1px solid var(--line-soft);
  border-radius: var(--r-md); padding: var(--sp-3) var(--sp-4); margin-bottom: var(--sp-4);
  color: var(--ink-1);
}
.fe__kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--sp-4); margin-bottom: var(--sp-6); }
.fe__kpi { display: flex; flex-direction: column; gap: var(--sp-1); padding: var(--sp-4); border: 1px solid var(--line-soft); border-radius: var(--r-md); }
.fe__kpi-v { font-family: var(--mono); font-size: var(--fs-xl); font-weight: 700; color: var(--accent); }
.fe__kpi-l { font-size: var(--fs-sm); color: var(--ink-2); }
.fe__tiers { margin-bottom: var(--sp-6); }
.fe__tiers-label { font-size: var(--fs-sm); color: var(--ink-2); }
.fe__bar { display: flex; height: 12px; border-radius: var(--r-sm); overflow: hidden; margin: var(--sp-2) 0; background: var(--line-soft); }
.fe__seg--high { background: var(--accent); }
.fe__seg--medium { background: var(--warn); }
.fe__seg--low { background: var(--ink-3); }
.fe__legend { display: flex; gap: var(--sp-4); font-size: var(--fs-sm); color: var(--ink-1); }
.fe__dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.fe__dot--high { background: var(--accent); }
.fe__dot--medium { background: var(--warn); }
.fe__dot--low { background: var(--ink-3); }
.fe__pnl { margin-bottom: var(--sp-6); border: 1px solid var(--line-soft); border-radius: var(--r-md); overflow: hidden; }
.fe__pnl-hd { padding: var(--sp-3) var(--sp-4); font-weight: 600; border-bottom: 1px solid var(--line-soft); }
.fe__table { width: 100%; border-collapse: collapse; }
.fe__table th, .fe__table td { padding: var(--sp-2) var(--sp-4); text-align: left; border-bottom: 1px solid var(--line-soft); font-size: var(--fs-sm); }
.fe__num { text-align: right; font-family: var(--mono); }
.fe__row--prod { background: var(--accent-subtle); }
.fe__empty { color: var(--ink-3); text-align: center; }
</style>
```

> token 名（`--sp-*`/`--ink-*`/`--accent`/`--warn`/`--r-md` 等）以 `static/css/tokens.css` 为单源；若某变量名在 tokens.css 不存在，用最接近的同族变量替换，**不要新造 token、不要写死颜色**。实现时对照 `BriefingPage.vue` 已用过的变量名。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/pages/forecast-eval/ForecastEvalPage.test.ts`
Expected: PASS（4 个测试：loading / missing / 有数据 / error）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/forecast-eval/ForecastEvalPage.vue frontend/src/pages/forecast-eval/ForecastEvalPage.test.ts
git commit -m "feat(forecast-eval): ForecastEvalPage.vue 页面组件"
```

---

## Task 6: 路由注册 + nav-items 翻 routeName

**Files:**
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/shell/nav-items.ts`
- Test: `frontend/src/shell/SidebarNav.test.ts`（真正覆盖 RouterLink/legacy href 的测试在这里，**不是** nav-items.test.ts）

- [ ] **Step 1: 加路由**

`frontend/src/router.ts` 的 `children` 数组里、briefing 那行之后加：

```typescript
        { path: "forecast-eval", name: "forecast-eval", component: () => import("./pages/forecast-eval/ForecastEvalPage.vue") },
```

- [ ] **Step 2: 翻 nav-items**

`frontend/src/shell/nav-items.ts` 把 forecast_eval 那行从

```typescript
  { id: "forecast_eval", label: "预测效果", icon: "sales", code: "09", legacyPageId: "forecast_eval" },
```

改为

```typescript
  { id: "forecast_eval", label: "预测效果", icon: "sales", code: "09", routeName: "forecast-eval" },
```

- [ ] **Step 3: 更新 SidebarNav 测试断言**

真正覆盖「已迁项=RouterLink / 未迁项=`<a href='/?page=id'>`」的是 `frontend/src/shell/SidebarNav.test.ts:32`（`nav-items.test.ts` 只有二选一不变量 + icon 断言，无 forecast-specific，本改动天然满足，无需动它）。

在 `SidebarNav.test.ts` 的第三个用例（「已迁项(briefing)=RouterLink…」）里追加对 forecast-eval 的断言——它现在应是 RouterLink，且不再出现在 legacy href 集合：

```typescript
  it("已迁项(briefing)=RouterLink；未迁项=<a href='/?page=id'>（无空格）", () => {
    const w = mountNav(true);
    const links = w.findAllComponents(RouterLinkStub);
    expect(links.some((l) => (l.props("to") as { name?: string })?.name === "briefing")).toBe(true);
    // forecast-eval 已迁 → 也是 RouterLink（routeName），不再走 legacy <a>
    expect(links.some((l) => (l.props("to") as { name?: string })?.name === "forecast-eval")).toBe(true);
    const hrefs = w.findAll("a.nav-item").map((a) => a.attributes("href"));
    expect(hrefs).toContain("/?page=restock");
    expect(hrefs).toContain("/?page=history");
    expect(hrefs).not.toContain("/?page=forecast_eval"); // 旧深链已退役
    hrefs.forEach((h) => h && expect(h).not.toContain(" "));
  });
```

- [ ] **Step 4: 跑前端全量测试**

Run: `cd frontend && npm run test`
Expected: PASS（含 nav-items、router 相关，全绿）

- [ ] **Step 5: typecheck**

Run: `cd frontend && npm run typecheck`
Expected: 退出码 0（vue-tsc 无错）

- [ ] **Step 6: 提交**

```bash
git add frontend/src/router.ts frontend/src/shell/nav-items.ts frontend/src/shell/SidebarNav.test.ts
git commit -m "feat(forecast-eval): vue-router 路由 + nav 翻 routeName"
```

---

## Task 7: 退役旧 SPA 标签

**Files:**
- Modify: `static/js/store.js`（旧 SPA 侧栏页面注册表真实源，**最关键**）
- Modify: `templates/index.html`
- Delete: `static/js/forecast_eval.js`

**退役决策（已定）：** 旧 forecast_eval 嵌在单体 SPA，无独立 Flask 路由，故无服务端 302 钩子。新壳已把 forecast_eval 翻成 `routeName`（不再有 UI 链接指向 `/?page=forecast_eval`）。

> **审查修正（关键）**：旧 SPA 侧栏的页面列表真实源是 `static/js/store.js:157-177` 的 `Alpine.store("nav").pages` 数组（**不是** index.html）。`store.js:168` 仍有 `{ id: "forecast_eval", label: "预测效果", ... }`。若只删 index.html 的 `#pageForecastEval` div + script，侧栏仍会渲染"预测效果"项 → 点击切到一个已被删空的 page → 用户落空页。**必须同时从 store.js 的 pages 数组删掉该行。**

删除三处后，`forecast_eval` 退出旧 SPA pageIds → 万一有人用旧书签 `/?page=forecast_eval`，`nav-resolve.js` 返回 null → 旧 SPA 落默认页（不崩、不留死链 UI）。内网单操作员场景，旧书签风险可接受，**本期不加客户端重定向**（YAGNI）。

- [ ] **Step 1（关键）: 从 store.js 的 pages 数组删 forecast_eval**

删除 `static/js/store.js` 第 168 行附近这一行（`Alpine.store("nav").pages` 数组内）：

```javascript
      { id: "forecast_eval",     label: "预测效果",   icon: "sales",      code: "09", shortcut: "9" },
```

> 删后该数组少一项，旧 SPA 侧栏不再渲染"预测效果"入口。`shortcut: "9"` 一并移除（该快捷键随之释放，无需补位）。

- [ ] **Step 2: 删 index.html 两处**

删除 `templates/index.html` 第 197 行附近：

```html
      <div class="page" id="pageForecastEval" x-data :class="$store.nav.current === 'forecast_eval' ? 'active' : ''"></div>
```

删除第 227 行附近：

```html
<script type="module" src="{{ url_for('static', filename='js/forecast_eval.js') }}"></script>
```

- [ ] **Step 3: 删 JS 文件**

```bash
git rm static/js/forecast_eval.js
```

- [ ] **Step 4: 验证旧 SPA 不再引用 forecast_eval**

Run: `grep -rn "forecast_eval\|pageForecastEval" templates/ static/js/`
Expected: 无输出（store.js / index.html / forecast_eval.js 三处已全摘；`forecast-eval` kebab 的新栈引用不在 templates/ 或 static/js/ 下，不受影响）

- [ ] **Step 5: 后端冒烟（index 仍能渲染 + 侧栏无"预测效果"）**

Run: `pytest e2e/test_smoke_nav.py::test_index_loads_no_console_error -v`
Expected: PASS（删 forecast_eval 标签后旧 SPA 首页仍无 console error）

人工补验（feedback：前端改动本地测试后再 push）：浏览器开旧 SPA，确认左侧栏不再出现"预测效果"项，且键入 `/?page=forecast_eval` 不落可点的空页（落默认页）。

> 若本地没装 Playwright/浏览器导致 e2e 跳过，改跑 `pytest tests/ -k "index or render" -q` 兜底；最终以 CI e2e 为准。

- [ ] **Step 6: 提交**

```bash
git add static/js/store.js templates/index.html
git commit -m "chore(forecast-eval): 退役旧 SPA 预测效果标签（store.js pages + index.html）"
```

---

## Task 8: 全量验收

- [ ] **Step 1: 后端全量测试**

Run: `pytest tests/ -q`
Expected: 全绿（新增 test_forecast_eval_api 3 个：401 契约 + 空库 + seeded；既有不回归）

- [ ] **Step 2: TS 类型漂移守护**

Run: `python tools/gen_ts_types.py --check`
Expected: 退出码 0

- [ ] **Step 3: 前端全量 + typecheck + build**

Run: `cd frontend && npm run test && npm run typecheck && npm run build`
Expected: vitest 全绿、vue-tsc 无错、vite build 成功

- [ ] **Step 4: 本地人工验证（feedback：前端改动本地测试后再 push）**

```bash
python server.py          # 后端，浏览器开 http://127.0.0.1:5000 确认旧 SPA 不再有「预测效果」标签且首页正常
# 另开终端：
cd frontend && npm run dev # 开 /ui，侧栏点「预测效果」→ 走 /ui/forecast-eval 渲染 Vue 页（不跳旧 SPA）
```

Expected:
- `/ui` 侧栏「预测效果」点击 → URL 变 `/ui/forecast-eval`，页面渲染 KPI/tier 条/两表（空库则显示「尚无回测数据」横幅 + 计数 0）
- 旧 SPA（:5000）侧栏不再有「预测效果」入口，首页无报错
- 浏览器 console 无 error

- [ ] **Step 5: 收尾**

- 更新 memory `project_frontend_decoupling.md`：第二个范式页 forecast_eval 已迁（§11 进度推进）。
- 按 `superpowers:finishing-a-development-branch` 决定合并方式（feedback：分支 + squash merge 回 main；合并前 `./test.ps1` 过本地 PG 腿 + 独立读到 CI 全绿再合）。
- **注意纪律**：若临近周一 14:00 scraper 窗口，禁 push main（Coolify auto-deploy 会杀后台任务）；前端 app 未开 auto-deploy，合并后 /ui 需手动 redeploy 或走 GH Action。

---

## 自审记录（spec/范式 覆盖核对）

1. **流水线覆盖**：pydantic schema(Task1) → gen_ts_types(Task2) → normalize 收窄(Task3) → store(Task4) → 组件(Task5) → router+nav(Task6) → 旧页退役(Task7) → 验收(Task8)。对齐简报迁移 + spec §11「旧页删除 + 不留死链 + e2e 烟雾更新」。
2. **占位符扫描**：每个 code step 含完整可粘贴代码；唯一「自己判断」点 = Task5 token 名兜底（以 tokens.css 为单源 + 对照 BriefingPage.vue），非逻辑占位。
3. **类型一致性**：`ForecastEvalData` 字段 = service 返回 + ok；`backtest_date`/`created_at` 用 `str | None`（已核 BacktestRun.created_at 列类型）；VM camelCase 映射在 normalize 单点完成；store/组件/测试引用的 VM 字段名（missing/runId/headline.beatsNaivePct/byType/models）全程一致。
4. **风险点**：`extra="forbid"` 要求 service 输出字段与 schema 完全一致——已逐字段核对 `build_forecast_eval_dashboard` 与 `_aggregate_metrics`/`_run_metrics` 输出（headline/by_sku_type/models/tiers 四块字段集匹配）。若 service 未来加字段，端点会 500（这是 §6 设计的漂移护栏，非 bug）。

---

## 审查修订记录（REQUEST_CHANGES → 已修，2026-06-17）

外部审查（Codex）提了 3 阻断 + 2 建议，逐条核实属实并已改入 plan：

| # | 类型 | 发现 | 核实 | 修复 |
|---|---|---|---|---|
| 1 | 阻断 | API 测试未登录期望 200，但 `app/auth.py:128-131` 对未登录 `/api/*` 返 401 | 属实 | Task1 测试改用 `tests/test_api_briefing.py` 范式（`X-Upload-Token`），并加未登录→401 契约测试 |
| 2 | 阻断 | seeded 测试漏多个 NOT NULL 字段（`ForecastOutput.model_used/mu/sigma/p50/p98`、`BacktestResult.n_weeks_train/n_weeks_test/bias/mean_actual/mean_predicted`） | 属实（`app/models.py:367-466`） | Task1 seed helper 逐字复制自 `tests/test_forecast_eval_dashboard.py:30-79`，字段填全 |
| 3 | 阻断 | 旧页退役漏了真实入口源 `static/js/store.js:168`（侧栏 pages 数组），只删 index.html 会留可点空页 | 属实 | Task7 加 Step 1：从 `store.js` pages 数组删 forecast_eval；git add 含 store.js；验证侧栏无"预测效果" |
| 4 | 建议 | RouterLink/legacy href 覆盖在 `SidebarNav.test.ts:32`，非 `nav-items.test.ts` | 属实 | Task6 改为更新 `SidebarNav.test.ts`，断言 forecast-eval=RouterLink 且 href 集合不含 `/?page=forecast_eval` |
| 5 | 建议 | Task5 组件测试用真 pinia 会触发真实 `onMounted().load()`；既有范式是 mock store plain object（`BriefingPage.test.ts:21`） | 属实 | Task5 测试改为 `vi.mock` store + plain `state` 对象，加 error 态用例 |
