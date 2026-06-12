# 前端独立化 阶段 0+1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 frontend/（Vue 3 + Vite + TS）独立工程地基并迁移简报页为试点，含 tokens 单源、Storybook、API 类型契约、401 认证分流与独立部署。

**Architecture:** 同仓 monorepo `frontend/` 子工程；Traefik 同域 PathPrefix(/ui) → 独立静态容器，其余 → Flask；新前端只消费 `/api/*`（试点 = `GET /api/briefing/data`，pydantic 校验 + 生成 TS 类型）；tokens 单源 = 现有 `static/css/tokens.css`，Vite `server.fs.allow` 跨 root 读取。

**Tech Stack:** Vue 3（`<script setup>` + TS）/ Pinia / Vue Router / Tailwind v4（@tailwindcss/vite）/ Vitest / Storybook 8 / pydantic / nginx。

**上游 spec:** `docs/superpowers/specs/2026-06-12-frontend-decoupling-design.md`（v4 已批准）。
四轮 review 的三条非阻断建议已吸收：Storybook `viteFinal` 同步 fs.allow（Task 9）、
fs.allow 绝对路径化（Task 4）、认证测试用完整 `server.create_app()`（Task 1/2）。

**执行纪律**：worktree + 分支 + PR；CI 必须**独立读到全绿后才允许单独执行 merge**；
绝不 push main；生产侧 Coolify 操作属用户手动步骤 = Task 13。

**事实修正**：spec §6 写"pydantic schema（app/schemas.py 先例）"——实际
`app/schemas.py` 是 **dataclass**。本 plan 决策：新 API schema 放独立 pydantic
模块 `app/schemas_api.py`，不在同一文件混两种范式。

---

### Task 0: 实施前置 — 根目录 package-lock.json 来源确认

**Files:**
- Delete（确认后）: `package-lock.json`（仓库根，untracked）

- [ ] **Step 1: 检查内容判定来源**

Run: `python -c "import json; d=json.load(open('package-lock.json',encoding='utf-8')); print(d.get('name'), list(d.get('packages',{}).keys())[:5])"`
Expected: name 为空/codegraph 相关 → npx 残留，可删。若出现任何业务相关包名 → **STOP，问用户**。

- [ ] **Step 2: 删除（仅当 Step 1 判定为残留）**

Run: `rm package-lock.json`；然后 `git status --short` 确认（剩 docs/thesis 论文 md 属用户文件不动）。
本 Task 无 commit（删的是 untracked 文件）。

---

### Task 1: 401 认证契约 — `_require_login` 按 /api/* 分流

**Files:**
- Modify: `app/auth.py:123-124`（仅 not authenticated 分支；X-Upload-Token 分支绝不触碰）
- Test: `tests/test_api_auth_contract.py`（新建）

- [ ] **Step 1: 写失败测试（完整 app，不许裸 blueprint）**

```python
"""API 401 认证契约 — spec §6 v3（完整 init_auth 闸集成测试）。"""

from __future__ import annotations

import pytest


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def test_unauthenticated_api_returns_json_401(real_app):
    r = real_app.test_client().get("/api/briefing/data")
    assert r.status_code == 401
    assert r.content_type.startswith("application/json")
    assert r.get_json() == {"error": "unauthenticated"}


def test_unauthenticated_page_still_redirects(real_app):
    r = real_app.test_client().get("/briefing")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_wrong_cron_token_still_loud_401(real_app):
    r = real_app.test_client().get("/briefing/data", headers={"X-Upload-Token": "wrong"})
    assert r.status_code == 401  # 响亮 4xx，绝不 302（#5 静默空转语义）


def test_correct_cron_token_passes_gate(real_app):
    r = real_app.test_client().get("/briefing/data", headers={"X-Upload-Token": "test-token-123"})
    assert r.status_code == 200
```

- [ ] **Step 2: 跑测试确认失败形态**

Run: `python -m pytest tests/test_api_auth_contract.py -v`
Expected: `test_unauthenticated_api_returns_json_401` FAIL（302 ≠ 401，此刻 /api/ 不存在也先被闸 302）；其余三条应已 PASS（守护现状）。

- [ ] **Step 3: 改 `_require_login`**

`app/auth.py` 当前（123-124 行）：

```python
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.url))
```

改为（仅插入 /api 分支，redirect 行原样保留）：

```python
        if not current_user.is_authenticated:
            # SPA fetch 不能吃 302 登录页 HTML（spec §6 v3）：/api/* 返回 JSON 401
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthenticated"}), 401
            return redirect(url_for("auth.login", next=request.url))
```

（`jsonify` 已在该文件 import；确认无则补。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_api_auth_contract.py tests/test_cron_forecast_auth.py -v`
Expected: 全 PASS（含既有 cron 鉴权测试不回归）。

- [ ] **Step 5: 全量回归 + commit**

Run: `python -m pytest tests/ -q`，Expected: 全绿。
```bash
git add app/auth.py tests/test_api_auth_contract.py
git commit -m "feat(auth): /api/* 未登录返回 JSON 401, 其余路径维持 302 (前端独立化 spec §6)"
```

---

### Task 2: pydantic schema + `GET /api/briefing/data`

**Files:**
- Create: `app/schemas_api.py`
- Modify: `app/routes/briefing.py`（追加 api 蓝图）、`app/routes/__init__.py`（注册）
- Test: `tests/test_api_briefing.py`（新建）

**核对过的数据形状**（briefing.py:427-434 实读）：envelope = `{ok, generated_at,
data_week(str|None), data_week_complete(bool), cards{5 个}, actions{3 个}}`；
cards.sales_health 形状稳定（briefing.py:118-165），其余 card/action 形状多态 →
v1 按 `dict` 透传（**显式决策**：类型化随前端组件消费逐步加深，不是占位符）。

- [ ] **Step 1: 写失败测试**

```python
"""GET /api/briefing/data — schema 校验 + 与旧端点数据一致（spec §6）。"""

from __future__ import annotations

import pytest


@pytest.fixture()
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def _get(app, path):
    return app.test_client().get(path, headers={"X-Upload-Token": "test-token-123"})


def test_api_briefing_data_matches_schema(real_app):
    r = _get(real_app, "/api/briefing/data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert set(body["cards"]) == {
        "sales_health", "restock_risk", "stockout_impact", "overstock_risk", "data_health",
    }
    assert set(body["actions"]) == {"restock", "follow_up", "review_anomalies"}


def test_api_briefing_consistent_with_legacy(real_app):
    new = _get(real_app, "/api/briefing/data").get_json()
    old = _get(real_app, "/briefing/data").get_json()
    # generated_at 是时间戳必然不同，其余字段必须一致（验收 #2 的测试态版本）
    for k in ("ok", "data_week", "data_week_complete", "cards", "actions"):
        assert new[k] == old[k], k
```

- [ ] **Step 2: 跑测试确认 404 失败**

Run: `python -m pytest tests/test_api_briefing.py -v`
Expected: 两条均 FAIL（404，端点不存在）。

- [ ] **Step 3: 写 `app/schemas_api.py`**

```python
"""API 响应 pydantic schema（前端独立化 spec §6）。

与 app/schemas.py（dataclass，进程内结构）分开：本模块只描述 HTTP API
契约，是 tools/gen_ts_types.py 的输入。新增 API 端点必须在此声明响应模型。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class BriefingCards(BaseModel):
    sales_health: dict[str, Any]
    restock_risk: dict[str, Any]
    stockout_impact: dict[str, Any]
    overstock_risk: dict[str, Any]
    data_health: dict[str, Any]


class BriefingActions(BaseModel):
    restock: dict[str, Any]
    follow_up: dict[str, Any]
    review_anomalies: dict[str, Any]


class BriefingData(BaseModel):
    """GET /api/briefing/data 响应。card/action 内层形状多态，v1 透传；
    前端组件消费到哪层，类型就加深到哪层（progressive typing）。"""

    ok: bool
    generated_at: str
    data_week: str | None
    data_week_complete: bool
    cards: BriefingCards
    actions: BriefingActions


# gen_ts_types.py 的导出清单：新增模型加进来即自动进 types.gen.ts
API_MODELS: list[type[BaseModel]] = [BriefingData]
```

- [ ] **Step 4: 加 api 蓝图**

`app/routes/briefing.py` 追加（文件尾部）：

```python
api_bp = Blueprint("api_briefing", __name__, url_prefix="/api/briefing")


@api_bp.get("/data")
def api_data():
    """canonical 简报端点（spec §6）。pydantic 校验 = schema 与现实漂移即 500。

    红线 B1 注记：computed_at 过期与 stockout_weeks_excluded 的处理在
    build_briefing 内部（data_health 卡新鲜度 + 置信分层输入），本端点
    是同一链路的再暴露，不引入新的 forecast_output 裸消费。
    """
    from app.schemas_api import BriefingData

    payload = briefing_service.build_briefing(
        as_of=_today(),
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )
    return jsonify(BriefingData.model_validate(payload).model_dump())
```

`app/routes/__init__.py`：在 `from app.routes.briefing import bp as briefing_bp` 同处加
`from app.routes.briefing import api_bp as briefing_api_bp`，在注册区加
`app.register_blueprint(briefing_api_bp)`。

- [ ] **Step 5: 跑测试通过 + 全量 + commit**

Run: `python -m pytest tests/test_api_briefing.py tests/test_api_auth_contract.py -v` → PASS；
`python -m pytest tests/ -q` → 全绿。
```bash
git add app/schemas_api.py app/routes/briefing.py app/routes/__init__.py tests/test_api_briefing.py
git commit -m "feat(api): GET /api/briefing/data — pydantic 契约端点 (canonical, spec §6)"
```

---

### Task 3: `tools/gen_ts_types.py` + `--check`

**Files:**
- Create: `tools/gen_ts_types.py`
- Create（生成物）: `frontend/src/api/types.gen.ts`
- Test: `tests/test_gen_ts_types.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
"""gen_ts_types — pydantic JSON Schema → TS 的轻量转换（spec §6）。"""

from __future__ import annotations

import subprocess
import sys


def test_generated_ts_contains_models(tmp_path):
    out = tmp_path / "types.gen.ts"
    r = subprocess.run(
        [sys.executable, "tools/gen_ts_types.py", "--out", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    ts = out.read_text(encoding="utf-8")
    assert "export interface BriefingData" in ts
    assert "data_week: string | null;" in ts
    assert "cards: BriefingCards;" in ts


def test_check_mode_detects_drift(tmp_path):
    out = tmp_path / "types.gen.ts"
    subprocess.run([sys.executable, "tools/gen_ts_types.py", "--out", str(out)], check=True)
    ok = subprocess.run([sys.executable, "tools/gen_ts_types.py", "--out", str(out), "--check"])
    assert ok.returncode == 0
    out.write_text("// drifted", encoding="utf-8")
    drift = subprocess.run([sys.executable, "tools/gen_ts_types.py", "--out", str(out), "--check"])
    assert drift.returncode != 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_gen_ts_types.py -v` → FAIL（脚本不存在）。

- [ ] **Step 3: 写转换脚本**

```python
"""pydantic JSON Schema → TypeScript 类型生成（自写轻量版，不引重型生成器）。

用法:
    python tools/gen_ts_types.py                 # 写 frontend/src/api/types.gen.ts
    python tools/gen_ts_types.py --check         # 漂移检查（CI 用，不一致退出码 1）
    python tools/gen_ts_types.py --out <path>    # 测试用自定义输出
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "frontend" / "src" / "api" / "types.gen.ts"
HEADER = "// 由 tools/gen_ts_types.py 生成 — 不要手改。来源: app/schemas_api.py\n\n"


def _ts_type(prop: dict, defs: dict) -> str:
    if "$ref" in prop:
        return prop["$ref"].split("/")[-1]
    if "anyOf" in prop:
        return " | ".join(sorted({_ts_type(p, defs) for p in prop["anyOf"]}))
    t = prop.get("type")
    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "array":
        return f"{_ts_type(prop.get('items', {}), defs)}[]"
    if t == "object":
        return "Record<string, unknown>"
    return "unknown"


def _interface(name: str, schema: dict, defs: dict) -> str:
    lines = [f"export interface {name} {{"]
    required = set(schema.get("required", []))
    for field, prop in (schema.get("properties") or {}).items():
        opt = "" if field in required else "?"
        lines.append(f"  {field}{opt}: {_ts_type(prop, defs)};")
    lines.append("}\n")
    return "\n".join(lines)


def generate() -> str:
    from app.schemas_api import API_MODELS

    blocks: list[str] = []
    emitted: set[str] = set()
    for model in API_MODELS:
        schema = model.model_json_schema()
        defs = schema.pop("$defs", {})
        for ref_name, ref_schema in defs.items():
            if ref_name not in emitted:
                emitted.add(ref_name)
                blocks.append(_interface(ref_name, ref_schema, defs))
        name = schema.get("title", model.__name__)
        if name not in emitted:
            emitted.add(name)
            blocks.append(_interface(name, schema, defs))
    return HEADER + "\n".join(blocks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    text = generate()
    if args.check:
        if not out.exists() or out.read_text(encoding="utf-8") != text:
            print(f"types.gen.ts 与 app/schemas_api.py 不一致，重跑 gen_ts_types.py: {out}")
            return 1
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 跑测试 + 生成首版 + commit**

Run: `python -m pytest tests/test_gen_ts_types.py -v` → PASS；
`python tools/gen_ts_types.py` → 写出 `frontend/src/api/types.gen.ts`。
```bash
git add tools/gen_ts_types.py tests/test_gen_ts_types.py frontend/src/api/types.gen.ts
git commit -m "feat(tools): pydantic→TS 类型生成 + --check 漂移检查 (spec §6)"
```

---

### Task 4: frontend/ 脚手架（Vite + Vue 3 + TS + Tailwind v4 + tokens）

**Files:**
- Create: `frontend/package.json`（经 npm 命令产生）、`frontend/vite.config.ts`、
  `frontend/tsconfig.json`、`frontend/index.html`、`frontend/.gitignore`、
  `frontend/src/main.ts`、`frontend/src/App.vue`、`frontend/src/router.ts`、
  `frontend/src/styles/main.css`、`frontend/src/pages/briefing/BriefingPage.vue`（占位）

- [ ] **Step 1: 初始化工程（版本由 npm 解析并锁进 lockfile，不手写钉死）**

```bash
mkdir frontend && cd frontend
npm init -y
npm install vue@^3 vue-router@^4 pinia@^3
npm install -D vite @vitejs/plugin-vue typescript vue-tsc tailwindcss @tailwindcss/vite vitest @vue/test-utils jsdom
```

- [ ] **Step 2: 写 `frontend/package.json` 的 scripts 块（命令名 = spec §5 定死）**

```json
"scripts": {
  "dev": "vite",
  "build": "vue-tsc --noEmit && vite build",
  "typecheck": "vue-tsc --noEmit",
  "test": "vitest run",
  "build-storybook": "storybook build"
}
```

（`build-storybook` 在 Task 9 安装 Storybook 前会失败，属预期；CI 在 Task 11 才接。）

- [ ] **Step 3: `frontend/vite.config.ts`（fs.allow 绝对路径 + /ui base + proxy）**

```typescript
import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
// 注意从 vitest/config 导入（配置里带 test 键，从 "vite" 导入会 TS 报错）
import { defineConfig } from "vitest/config";

// 仓库根（绝对路径，避免 Windows/Linux 相对解析差异 — review 建议）
const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const frontendRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  base: "/ui/",
  plugins: [vue(), tailwindcss()],
  server: {
    fs: {
      // tokens 单源在仓库根 static/css/，跨 frontend root 读取（spec §7 v4）
      allow: [frontendRoot, repoRoot],
    },
    proxy: {
      "/api": { target: "http://127.0.0.1:5000", changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
  },
});
```

- [ ] **Step 4: 其余脚手架文件**

`frontend/tsconfig.json`：

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "jsx": "preserve",
    "noEmit": true,
    "types": ["vite/client"],
    "skipLibCheck": true
  },
  "include": ["src/**/*.ts", "src/**/*.vue", "vite.config.ts"]
}
```

`frontend/.gitignore`：

```
node_modules/
dist/
storybook-static/
```

`frontend/index.html`：

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>label-sync</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

`frontend/src/styles/main.css`（tokens 单源消费 + @theme 映射 = 新栈私有）：

```css
/* 单源 tokens：仓库根 static/css/tokens.css（spec §7 — 绝不复制） */
@import "../../../static/css/tokens.css";
@import "tailwindcss";

/* @theme 映射层：把单源 CSS 变量暴露成 Tailwind 工具类（新栈私有，不回写单源） */
@theme {
  --spacing-1: var(--sp-1);
  --spacing-2: var(--sp-2);
  --spacing-3: var(--sp-3);
  --spacing-4: var(--sp-4);
  --spacing-6: var(--sp-6);
  --font-size-sm: var(--fs-sm);
  --font-size-base: var(--fs-base);
  --font-size-lg: var(--fs-lg);
  --font-size-xl: var(--fs-xl);
}
```

（色彩/圆角/阴影变量名在执行时打开 `static/css/tokens.css` 对照补齐——映射键
必须指向真实存在的变量，**不许发明变量名**。）

`frontend/src/main.ts`：

```typescript
import { createPinia } from "pinia";
import { createApp } from "vue";
import App from "./App.vue";
import { router } from "./router";
import "./styles/main.css";

createApp(App).use(createPinia()).use(router).mount("#app");
```

`frontend/src/router.ts`：

```typescript
import { createRouter, createWebHistory } from "vue-router";

export const router = createRouter({
  history: createWebHistory("/ui/"),
  routes: [
    { path: "/", redirect: "/briefing" },
    {
      path: "/briefing",
      component: () => import("./pages/briefing/BriefingPage.vue"),
    },
  ],
});
```

`frontend/src/App.vue`：

```vue
<template>
  <RouterView />
</template>
```

`frontend/src/pages/briefing/BriefingPage.vue`（占位，Task 7 替换）：

```vue
<template>
  <div>briefing placeholder</div>
</template>
```

- [ ] **Step 5: 验证 dev/build 跨 root tokens 生效（验收 #1/#6 前两段）**

Run: `cd frontend && npm run dev` → 浏览器开 http://localhost:5173/ui/ 无
"outside of Vite serving allow list" 报错。
Run: `npm run build` → dist 产出；`grep -r "sp-4" dist/assets/*.css` 命中 token 变量。

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): Vite+Vue3+TS 脚手架 — /ui base + fs.allow 跨 root tokens + /api proxy"
```

---

### Task 5: API client（401/redirect 防御）

**Files:**
- Create: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`

- [ ] **Step 1: 写失败测试**

```typescript
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiGet, UnauthenticatedError } from "./client";

function mockResponse(init: Partial<Response> & { json?: unknown }) {
  return {
    ok: true,
    status: 200,
    redirected: false,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => init.json ?? {},
    ...init,
  } as unknown as Response;
}

afterEach(() => vi.unstubAllGlobals());

describe("apiGet", () => {
  it("返回 JSON 数据", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => mockResponse({ json: { ok: true } })));
    expect(await apiGet("/api/briefing/data")).toEqual({ ok: true });
  });

  it("401 → 跳登录并抛 UnauthenticatedError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => mockResponse({ ok: false, status: 401 })));
    const assign = vi.fn();
    vi.stubGlobal("location", { assign, pathname: "/ui/briefing" });
    await expect(apiGet("/x")).rejects.toBeInstanceOf(UnauthenticatedError);
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fui%2Fbriefing");
  });

  it("text/html 响应按未登录处理（防 302 喂登录页）", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      mockResponse({ redirected: true, headers: new Headers({ "content-type": "text/html" }) }),
    ));
    const assign = vi.fn();
    vi.stubGlobal("location", { assign, pathname: "/ui/briefing" });
    await expect(apiGet("/x")).rejects.toBeInstanceOf(UnauthenticatedError);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm test` → FAIL（client.ts 不存在）。

- [ ] **Step 3: 实现**

```typescript
export class UnauthenticatedError extends Error {}

/** 统一 API GET：same-origin cookie；401/redirect/HTML 一律按未登录跳转（spec §6）。 */
export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  const isHtml = (res.headers.get("content-type") ?? "").includes("text/html");
  if (res.status === 401 || res.redirected || isHtml) {
    location.assign(`/login?next=${encodeURIComponent(location.pathname)}`);
    throw new UnauthenticatedError(`unauthenticated: ${path}`);
  }
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return (await res.json()) as T;
}
```

- [ ] **Step 4: 跑测试通过 + commit**

Run: `npm test` → 3 passed。
```bash
git add frontend/src/api/
git commit -m "feat(frontend): apiGet 封装 — 401/redirect/HTML 三态未登录防御"
```

---

### Task 6: 基础组件（Card / Badge / PageHeader）

**Files:**
- Create: `frontend/src/components/Card.vue`、`Badge.vue`、`PageHeader.vue`
- Test: `frontend/src/components/components.test.ts`

- [ ] **Step 1: 写失败测试**

```typescript
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import Badge from "./Badge.vue";
import Card from "./Card.vue";
import PageHeader from "./PageHeader.vue";

describe("基础组件", () => {
  it("Card 渲染标题与默认插槽", () => {
    const w = mount(Card, { props: { title: "销售健康" }, slots: { default: "<p>body</p>" } });
    expect(w.text()).toContain("销售健康");
    expect(w.html()).toContain("<p>body</p>");
  });

  it("Badge 按 tone 切换样式类", () => {
    const ok = mount(Badge, { props: { tone: "ok" }, slots: { default: "正常" } });
    const warn = mount(Badge, { props: { tone: "warn" }, slots: { default: "注意" } });
    expect(ok.classes()).not.toEqual(warn.classes());
    expect(ok.text()).toBe("正常");
  });

  it("PageHeader 渲染标题与副标题", () => {
    const w = mount(PageHeader, { props: { title: "晨间简报", subtitle: "2026-06-08 周" } });
    expect(w.text()).toContain("晨间简报");
    expect(w.text()).toContain("2026-06-08");
  });
});
```

- [ ] **Step 2: 跑测试失败** → `npm test` FAIL（组件不存在）。

- [ ] **Step 3: 实现三个组件（样式只用 token 变量，不写裸色值）**

`Card.vue`：

```vue
<script setup lang="ts">
defineProps<{ title: string }>();
</script>

<template>
  <section class="card">
    <h3 class="card-title">{{ title }}</h3>
    <slot />
  </section>
</template>

<style scoped>
.card {
  background: var(--surface-1);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-md);
  padding: var(--sp-4);
}
.card-title {
  font-size: var(--fs-lg);
  margin: 0 0 var(--sp-3);
}
</style>
```

`Badge.vue`：

```vue
<script setup lang="ts">
withDefaults(defineProps<{ tone?: "ok" | "warn" | "danger" | "muted" }>(), { tone: "muted" });
</script>

<template>
  <span class="badge" :class="`badge--${tone}`"><slot /></span>
</template>

<style scoped>
.badge {
  display: inline-block;
  padding: 0 var(--sp-2);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
}
.badge--ok { color: var(--color-ok); }
.badge--warn { color: var(--color-warn); }
.badge--danger { color: var(--color-danger); }
.badge--muted { color: var(--text-2); }
</style>
```

`PageHeader.vue`：

```vue
<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>();
</script>

<template>
  <header class="page-header">
    <h1>{{ title }}</h1>
    <p v-if="subtitle">{{ subtitle }}</p>
  </header>
</template>

<style scoped>
.page-header h1 { font-size: var(--fs-2xl); margin: 0; }
.page-header p { color: var(--text-2); margin: var(--sp-1) 0 0; }
</style>
```

（`--surface-1/--border-1/--radius-*/--color-ok/--text-2` 等变量名执行时对照
`static/css/tokens.css` 真实名称替换——同 Task 4 的"不许发明变量名"约束；
若 tokens.css 缺语义色变量，按 spec §7 允许补进单源并在 commit 注明。）

- [ ] **Step 4: 跑测试通过 + commit**

`npm test` → passed。
```bash
git add frontend/src/components/
git commit -m "feat(frontend): Card/Badge/PageHeader 基础组件 (token-only 样式)"
```

---

### Task 7: 简报页（Pinia store + 页面）

**Files:**
- Create: `frontend/src/stores/briefing.ts`
- Modify: `frontend/src/pages/briefing/BriefingPage.vue`（替换 Task 4 占位）
- Test: `frontend/src/stores/briefing.test.ts`

- [ ] **Step 1: 写失败测试（store 层，mock apiGet）**

```typescript
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", () => ({
  apiGet: vi.fn(async () => ({
    ok: true,
    generated_at: "2026-06-12T09:00:00",
    data_week: "2026-06-08",
    data_week_complete: true,
    cards: {
      sales_health: { ok: true, status: "ok" },
      restock_risk: { ok: true },
      stockout_impact: { ok: true },
      overstock_risk: { ok: true },
      data_health: { ok: true },
    },
    actions: { restock: { items: [] }, follow_up: { items: [] }, review_anomalies: { items: [] } },
  })),
}));

import { useBriefingStore } from "./briefing";

describe("briefing store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("load 填充数据并清 loading", async () => {
    const s = useBriefingStore();
    expect(s.loading).toBe(false);
    const p = s.load();
    expect(s.loading).toBe(true);
    await p;
    expect(s.loading).toBe(false);
    expect(s.data?.data_week).toBe("2026-06-08");
    expect(s.error).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试失败** → `npm test` FAIL。

- [ ] **Step 3: 实现 store**

```typescript
import { defineStore } from "pinia";
import { ref } from "vue";
import { apiGet } from "../api/client";
import type { BriefingData } from "../api/types.gen";

export const useBriefingStore = defineStore("briefing", () => {
  const data = ref<BriefingData | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function load() {
    loading.value = true;
    error.value = null;
    try {
      data.value = await apiGet<BriefingData>("/api/briefing/data");
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  return { data, loading, error, load };
});
```

- [ ] **Step 4: 实现页面（替换占位）**

```vue
<script setup lang="ts">
import { onMounted } from "vue";
import Badge from "../../components/Badge.vue";
import Card from "../../components/Card.vue";
import PageHeader from "../../components/PageHeader.vue";
import { useBriefingStore } from "../../stores/briefing";

const store = useBriefingStore();
onMounted(() => store.load());

const cardTitles: Record<string, string> = {
  sales_health: "销售健康",
  restock_risk: "补货风险",
  stockout_impact: "缺货影响",
  overstock_risk: "压货风险",
  data_health: "数据健康",
};
</script>

<template>
  <main class="briefing">
    <PageHeader
      title="晨间简报"
      :subtitle="store.data ? `数据周 ${store.data.data_week ?? '—'}` : undefined"
    />
    <p v-if="store.loading">加载中…</p>
    <p v-else-if="store.error" class="error">{{ store.error }}</p>
    <div v-else-if="store.data" class="cards">
      <Card v-for="(card, key) in store.data.cards" :key="key" :title="cardTitles[key] ?? key">
        <Badge :tone="card.ok ? 'ok' : 'danger'">{{ card.ok ? "正常" : "异常" }}</Badge>
        <pre class="card-raw">{{ card }}</pre>
      </Card>
    </div>
  </main>
</template>

<style scoped>
.briefing { padding: var(--sp-6); max-width: 1100px; margin: 0 auto; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: var(--sp-4); }
.error { color: var(--color-danger); }
.card-raw { font-size: var(--fs-sm); overflow: auto; }
</style>
```

（**显式决策**：卡片内层先 `<pre>` 原样展示——阶段 0+1 验收的是架构链路与
数据一致性，视觉精修是后续 PR，防止架构验证和 UI 打磨混在一起。）

- [ ] **Step 5: 全套前端验证 + commit**

Run: `npm test` → 全 passed；`npm run typecheck` → 0 错误；`npm run build` → 成功。
本地双进程验证：`python server.py` + `npm run dev` → http://localhost:5173/ui/briefing
登录态下渲染五张卡（验收 #1 手验）。
```bash
git add frontend/src/
git commit -m "feat(frontend): 简报试点页 — Pinia store + 五卡渲染 (类型来自 types.gen)"
```

---

### Task 8: 旧栈零回归检查点（无新代码）

- [ ] **Step 1: 确认零回归**

Run: `python -m pytest tests/ -q` → 全绿；`git diff main --stat -- templates/ static/`
→ 仅 `static/css/tokens.css` 可能有补充变量（Task 6 注明的情况），无其他旧栈改动。
旧简报页 `/briefing` 行为由 Task 1 的 302 测试 + Task 2 的一致性测试守护。

---

### Task 9: Storybook（含 viteFinal fs.allow 同步）

**Files:**
- Create: `frontend/.storybook/main.ts`、`frontend/.storybook/preview.ts`、
  `frontend/src/components/Card.stories.ts`、`Badge.stories.ts`、`PageHeader.stories.ts`、
  `frontend/src/styles/Tokens.stories.ts`

- [ ] **Step 1: 安装**

```bash
cd frontend && npx storybook@8 init --type vue3 --builder vite --no-dev
```

（init 生成的示例 stories 删除；`.storybook/` 下两个文件按下面内容覆盖。）

- [ ] **Step 2: `.storybook/main.ts`（关键：viteFinal 同步 fs.allow —— 四轮 review 建议）**

```typescript
import { fileURLToPath, URL } from "node:url";
import type { StorybookConfig } from "@storybook/vue3-vite";

const config: StorybookConfig = {
  framework: "@storybook/vue3-vite",
  stories: ["../src/**/*.stories.ts"],
  async viteFinal(cfg) {
    // Storybook 的 Vite builder 不继承 vite.config.ts 的 server.fs.allow —
    // 跨 root 读 ../static/css/tokens.css 必须在此重复放行（spec 四轮 review）
    cfg.server = cfg.server ?? {};
    cfg.server.fs = {
      ...cfg.server.fs,
      allow: [
        fileURLToPath(new URL("..", import.meta.url)),
        fileURLToPath(new URL("../..", import.meta.url)),
      ],
    };
    return cfg;
  },
};
export default config;
```

`.storybook/preview.ts`：

```typescript
import "../src/styles/main.css";
```

- [ ] **Step 3: stories（每个基础组件一个 + tokens 可视化）**

`frontend/src/components/Card.stories.ts`：

```typescript
import type { Meta, StoryObj } from "@storybook/vue3";
import Card from "./Card.vue";

const meta: Meta<typeof Card> = { component: Card, title: "基础/Card" };
export default meta;

export const Default: StoryObj<typeof Card> = {
  render: () => ({
    components: { Card },
    template: `<Card title="销售健康"><p>卡片内容</p></Card>`,
  }),
};
```

`frontend/src/components/Badge.stories.ts`：

```typescript
import type { Meta, StoryObj } from "@storybook/vue3";
import Badge from "./Badge.vue";

const meta: Meta<typeof Badge> = { component: Badge, title: "基础/Badge" };
export default meta;

export const 四态: StoryObj<typeof Badge> = {
  render: () => ({
    components: { Badge },
    template: `
      <div style="display:flex;gap:8px">
        <Badge tone="ok">正常</Badge>
        <Badge tone="warn">注意</Badge>
        <Badge tone="danger">异常</Badge>
        <Badge tone="muted">无数据</Badge>
      </div>`,
  }),
};
```

`frontend/src/components/PageHeader.stories.ts`：

```typescript
import type { Meta, StoryObj } from "@storybook/vue3";
import PageHeader from "./PageHeader.vue";

const meta: Meta<typeof PageHeader> = { component: PageHeader, title: "基础/PageHeader" };
export default meta;

export const 带副标题: StoryObj<typeof PageHeader> = {
  args: { title: "晨间简报", subtitle: "数据周 2026-06-08" },
};

export const 仅标题: StoryObj<typeof PageHeader> = {
  args: { title: "晨间简报" },
};
```

`frontend/src/styles/Tokens.stories.ts`（间距/字号表；tokens.css 有语义色则同模式加色板）：

```typescript
import type { Meta, StoryObj } from "@storybook/vue3";

const meta: Meta = { title: "规范/Tokens" };
export default meta;

const SPACINGS = ["--sp-1", "--sp-2", "--sp-3", "--sp-4", "--sp-5", "--sp-6", "--sp-7", "--sp-8"];
const FONTS = ["--fs-xs", "--fs-sm", "--fs-md", "--fs-base", "--fs-lg", "--fs-xl", "--fs-2xl"];

export const 间距与字号: StoryObj = {
  render: () => ({
    setup: () => ({ SPACINGS, FONTS }),
    template: `
      <div>
        <h3>spacing（8pt grid）</h3>
        <div v-for="v in SPACINGS" :key="v" style="display:flex;gap:8px;align-items:center">
          <code style="width:80px">{{ v }}</code>
          <div :style="{ width: 'var(' + v + ')', height: '12px', background: 'currentColor' }" />
        </div>
        <h3>font sizes</h3>
        <p v-for="v in FONTS" :key="v" :style="{ fontSize: 'var(' + v + ')' }">{{ v }} — 简报示例文字</p>
      </div>`,
  }),
};
```

- [ ] **Step 4: 验证 + commit**

Run: `npm run build-storybook` → 成功（storybook-static/ 产出，已在 .gitignore）。
```bash
git add frontend/.storybook frontend/src/components/*.stories.ts frontend/src/styles/Tokens.stories.ts frontend/package.json frontend/package-lock.json
git commit -m "feat(frontend): Storybook 8 — 基础组件 stories + tokens 可视化 + viteFinal fs.allow"
```

---

### Task 10: 部署工件（Dockerfile + nginx）

**Files:**
- Create: `frontend/Dockerfile`、`frontend/nginx.conf`

- [ ] **Step 1: `frontend/nginx.conf`（/ui 子目录 + SPA fallback，spec §2）**

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;

    location /ui/ {
        try_files $uri /ui/index.html;
    }

    location = / {
        return 302 /ui/;
    }
}
```

- [ ] **Step 2: `frontend/Dockerfile`（多阶段；构建上下文 = 仓库根，因要带 static/css）**

```dockerfile
# 构建上下文必须是仓库根（tokens 单源在 static/css/）：
#   docker build -f frontend/Dockerfile .
FROM node:22-alpine AS build
WORKDIR /repo
COPY static/css/ static/css/
COPY frontend/ frontend/
WORKDIR /repo/frontend
RUN npm ci && npm run build

FROM nginx:alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/frontend/dist/ /usr/share/nginx/html/ui/
```

- [ ] **Step 3: 本地验证（验收 #9/#10 本地版）**

```bash
docker build -f frontend/Dockerfile -t label-sync-ui:dev .
docker run --rm -d -p 8080:80 --name ui-dev label-sync-ui:dev
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://localhost:8080/ui/briefing
ls frontend/dist/assets/*.js | head -1   # 取一个真实 hash 文件名
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://localhost:8080/ui/assets/<上一步的文件名>
docker stop ui-dev
```

Expected: `/ui/briefing` → `200 text/html`（fallback）；`/ui/assets/<hash>.js` → `200` 且 content-type 含 `javascript`。

- [ ] **Step 4: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf
git commit -m "feat(deploy): 前端独立镜像 — nginx /ui 子目录 + SPA fallback"
```

---

### Task 11: CI frontend job + 根目录无 Node 守护

**Files:**
- Modify: `.github/workflows/ci.yml`（追加 job；现有 test/docker 两 job 不动）

- [ ] **Step 1: 追加 job**

```yaml
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: 根目录无 Node 守护（spec 验收 12）
        run: |
          test ! -f package.json && test ! -f package-lock.json
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - name: Install
        working-directory: frontend
        run: npm ci
      - name: Typecheck
        working-directory: frontend
        run: npm run typecheck
      - name: Unit tests (vitest run)
        working-directory: frontend
        run: npm test
      - name: Build
        working-directory: frontend
        run: npm run build
      - name: Storybook build
        working-directory: frontend
        run: npm run build-storybook
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: TS 类型与 pydantic schema 漂移检查
        run: |
          pip install pydantic
          python tools/gen_ts_types.py --check
```

- [ ] **Step 2: 本地预检 + commit**

Run: `cd frontend && npm ci && npm run typecheck && npm test && npm run build && npm run build-storybook && cd .. && python tools/gen_ts_types.py --check` 全部退出码 0。
```bash
git add .github/workflows/ci.yml
git commit -m "ci: frontend job — typecheck/vitest/build/storybook + 根目录无 Node 守护 + 类型漂移检查"
```

---

### Task 12: dev.ps1 -Frontend 开关 + 指令文档

**Files:**
- Modify: `dev.ps1`、`CLAUDE.md`、`AGENTS.md`、`README.md`

- [ ] **Step 1: dev.ps1 追加 `-Frontend` 开关**

在现有 `param(...)` 块追加 `[switch]$Frontend`（**对照现有参数合并，勿覆盖**），
在现有启动逻辑之后追加：

```powershell
if ($Frontend) {
    Start-Process pwsh -ArgumentList "-NoExit", "-Command", "Set-Location '$PSScriptRoot\frontend'; npm run dev"
    Write-Host "前端 dev server: http://localhost:5173/ui/  (proxy /api -> :5000)"
}
```

- [ ] **Step 2: CLAUDE.md / AGENTS.md 增补**（两处同步，插在"编码规范"节后）

```markdown
## 前端独立化（阶段 0+1 试点期）

- 新 API 端点：响应模型声明在 `app/schemas_api.py`（pydantic），改后跑
  `python tools/gen_ts_types.py` 同步 TS 类型（CI --check 守护漂移）
- `/api/*` 未登录返回 JSON 401（auth.py `_require_login` 分流）；
  X-Upload-Token cron 分支语义不可动
- frontend/ 是独立 Vite 工程（Node 严格圈在该目录，仓库根禁 package.json）；
  本地 `./dev.ps1 -Frontend` 或 `cd frontend && npm run dev`
- tokens 单源 = `static/css/tokens.css`（纯 CSS 变量），新栈经
  frontend/src/styles/main.css 的 @theme 映射消费——绝不复制该文件
- 设计 spec：docs/superpowers/specs/2026-06-12-frontend-decoupling-design.md
```

README.md 在功能模块表后加一行：
`> 前端独立化试点：新版简报页 `/ui/briefing`（Vue 3，见 frontend/）。`

- [ ] **Step 3: 全量回归 + commit**

`python -m pytest tests/ -q` 全绿。
```bash
git add dev.ps1 CLAUDE.md AGENTS.md README.md
git commit -m "docs+dev: -Frontend 开关 + 前端独立化试点期规范进指令文档"
```

---

### Task 13: PR 合并 + 生产部署（用户协作步骤）

- [ ] **Step 1: PR 流程**

push 分支 → `gh pr create`（描述含 spec §10 验收清单勾选状态）→
`gh pr checks <N> --watch` **独立读到全部 job 全绿**（python 三腿 + 新 frontend
腿）→ 下一条命令单独执行 `gh pr merge <N> --squash --delete-branch`。

- [ ] **Step 2: Coolify 配置（用户手动，向用户输出操作单）**

1. Coolify 新建 app：同仓库，Build Pack = Dockerfile，Dockerfile 路径
   `frontend/Dockerfile`，**Build Context = 仓库根**
2. Traefik 规则：该 app 配 `PathPrefix(/ui)`（域名与 Flask app 相同）
3. watch paths（若版本支持）：前端 app = `frontend/**` + `static/css/**`；
   后端 app 排除 `frontend/**`
4. 部署后生产验收：spec §10 的 #2/#3/#9/#10/#11（curl 命令照 Task 10 Step 3
   换生产域名）+ 改一个 token 色值走完整发布验证 #6 第三段

- [ ] **Step 3: 验收勾选与收尾**

spec §10 十二条逐条勾选；全过 → spec 状态改"已验收"，CLAUDE.md 双栈期规范
去掉"试点期"字样转正式；记忆更新前端独立化进度。
未全过 → 缺哪条修哪条，不带病排后续页面迁移。
