# 货号历史 Phase 4c（退役旧 SPA 页）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 退役旧 Alpine 货号历史页及其专属 `/recent_changes/*` 蓝图与「查看完整分析（旧版）」深链，收官货号历史 Vue 迁移；`/scan_history/*` 全部保留（新页+标签页共用）；旧书签 `/?page=history` 走服务端 302 落 `/ui/history`。

**Architecture:** 纯删除/退役任务。**任务顺序保证原子性**：先删前端深链（独立）→ 先就位 302 兜底 → 删旧 SPA 页（含调用 `/recent_changes/*` 的 JS）→ 最后删 `recent_changes` 蓝图（此时已无调用方，不会出现「页在调、端点 404」的中间提交）。零新功能、零数据逻辑、零 schema 变更。

**Tech Stack:** Flask 蓝图、Jinja 模板、Vanilla JS（旧 SPA）、Vue 3 + Vitest（新页）、pytest。

设计：`docs/superpowers/specs/2026-06-20-history-vue-phase4c-retire-design.md`

---

### Task 1: 删除新 Vue 页「查看完整分析（旧版）」深链（D11/D12/T2）

**Files:**
- Modify: `frontend/src/pages/history/HistoryPage.vue:143-146`
- Test: `frontend/src/pages/history/HistoryPage.test.ts:92-99`

- [ ] **Step 1: 反转测试——断言深链不存在**

把 `HistoryPage.test.ts` 第 92-99 行那个测试整体替换为：

```ts
  it("初始态：提示输入 + 不再有「完整分析（旧版）」深链（4c 退役）", () => {
    reset();
    const w = mount(HistoryPage);
    expect(w.text()).toContain("输入条码");
    expect(w.find("a.history__legacy-link").exists()).toBe(false);
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts -t "4c 退役"`
Expected: FAIL —— 链接仍在 DOM，`exists()` 返回 true。

- [ ] **Step 3: 删除深链 + 改副标题**

`HistoryPage.vue` 当前：

```html
    <PageHeader title="货号历史" subtitle="核心查询 / 变更溯源（完整分析见旧版）" />

    <!-- HC-1 安全阀：完整分析旧版深链 -->
    <a class="history__legacy-link" href="/?page=history">查看完整分析（旧版）→</a>
```

改为（删掉注释 + `<a>` 两行，副标题去「见旧版」）：

```html
    <PageHeader title="货号历史" subtitle="核心查询 · 完整分析 · 批次记录" />
```

同时删除该组件 `<style>` 里 `.history__legacy-link` 的样式规则（搜 `history__legacy-link`，整条删除；若无则跳过）。

- [ ] **Step 4: 跑测试确认通过 + typecheck**

Run: `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts && npx vue-tsc --noEmit`
Expected: PASS（全部 HistoryPage 测试绿）+ typecheck 0 error。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/history/HistoryPage.vue frontend/src/pages/history/HistoryPage.test.ts
git commit -m "refactor(history): 删除货号历史旧版深链安全阀（4c）"
```

---

### Task 2: `/?page=history` 服务端 302 → `/ui/history`（A1，旧书签兼容）

**Files:**
- Modify: `app/routes/pages_tasks.py:3`（import）+ `:37-43`（`index()`）
- Test: `tests/test_history_legacy_redirect.py`（新建）

> 顺序在删旧 SPA 页之前：302 先就位，删页后旧书签立即被兜底，无空窗。

> **认证注意（审查实测）**：本项目 `_require_login` 是自定义 `before_request`（`app/auth.py:101`），未登录浏览器请求一律 302 到 `/login?next=...`——`LOGIN_DISABLED` **无效**。必须用 seed admin 建认证 session（套路照搬已验证的 `tests/test_index_render_smoke.py`）。

- [ ] **Step 1: 写失败测试——`/?page=history` 已登录态应 302 到 `/ui/history`**

新建 `tests/test_history_legacy_redirect.py`：

```python
"""Phase 4c：旧书签 /?page=history 服务端 302 兜底到 /ui/history。

认证套路照搬 tests/test_index_render_smoke.py（seed admin + session_transaction）。
"""

from urllib.parse import parse_qs, urlparse

import pytest


@pytest.fixture
def real_app(monkeypatch):
    monkeypatch.setenv("UPLOAD_TOKEN", "test-token-123")
    from server import create_app

    app = create_app(seed_auth=True, prewarm=False)
    app.config["TESTING"] = True
    return app


def _login(app, client):
    with app.app_context():
        from app.db import get_session
        from app.models import User

        with get_session() as s:
            admin = s.query(User).filter_by(role="admin").first()
            aid = str(admin.id)
    with client.session_transaction() as sess:
        sess["_user_id"] = aid
        sess["_fresh"] = True


def test_page_history_redirects_to_vue(real_app):
    client = real_app.test_client()
    _login(real_app, client)
    resp = client.get("/?page=history")
    assert resp.status_code == 302
    # 精确断言 path（兼容 Werkzeug 相对/绝对 Location 两种形态）
    assert urlparse(resp.headers["Location"]).path == "/ui/history"


def test_root_and_other_pages_not_redirected(real_app):
    """普通首页 / 与其它 page 不被重定向（仍渲染 SPA → 200）。"""
    client = real_app.test_client()
    _login(real_app, client)
    assert client.get("/").status_code == 200
    assert client.get("/?page=main").status_code == 200


def test_unauthenticated_history_bookmark_round_trips_to_vue(real_app):
    """完整回跳链：未登录 → 登录闸 302 到 /login（next 保留旧书签）→ 登录后重放 → 再 302 到 Vue。"""
    client = real_app.test_client()
    resp = client.get("/?page=history")  # 未登录
    assert resp.status_code == 302
    loc = urlparse(resp.headers["Location"])
    assert loc.path.endswith("/login")
    # next 须保留原 URL（含 page=history），登录后才能回跳
    next_url = parse_qs(loc.query).get("next", [""])[0]
    assert "page=history" in next_url
    # 登录后重放原 URL → 命中 index() 的 302
    _login(real_app, client)
    resp2 = client.get("/?page=history")
    assert resp2.status_code == 302
    assert urlparse(resp2.headers["Location"]).path == "/ui/history"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_history_legacy_redirect.py -q`
Expected: FAIL —— 已登录 `/?page=history` 当前返回 200（渲染 SPA），非 302（`test_page_history_redirects_to_vue` 与 round-trip 的第二段红；未登录段已 PASS）。

- [ ] **Step 3: 在 index() 加 302 特判**

`app/routes/pages_tasks.py` 第 3 行 import 加 `redirect`：

```python
from flask import Blueprint, jsonify, redirect, render_template, request, send_file
```

`index()` 改为（保持原 render 不变，仅前置特判）：

```python
@bp.get("/")
def index():
    # Phase 4c：旧书签 /?page=history → Vue 页（其余 page=* 仍交客户端 SPA）
    if request.args.get("page") == "history":
        return redirect("/ui/history", code=302)
    return render_template(
        "index.html",
        enable_transfer=CONFIG.enable_transfer,
        is_admin=(getattr(current_user, "role", None) == "admin"),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_history_legacy_redirect.py -q`
Expected: PASS（三条均绿）。

- [ ] **Step 5: ruff + commit**

Run: `ruff check app/routes/pages_tasks.py tests/test_history_legacy_redirect.py && ruff format --check app/routes/pages_tasks.py tests/test_history_legacy_redirect.py`
Expected: clean（import 已按 isort 序 `parse_qs, urlparse`，无 I001）。

```bash
git add app/routes/pages_tasks.py tests/test_history_legacy_redirect.py
git commit -m "feat(history): /?page=history 服务端 302 兜底到 /ui/history（4c 旧书签）"
```

---

### Task 3: 删除旧 SPA 货号历史页文件 + nav 条目（D1-D7）+ 守护反转（T1）

**Files:**
- Delete: `templates/partials/_page_history.html`
- Delete: `static/js/history.js`
- Delete: `static/js/index-recent-changes.js`
- Delete: `static/js/index-scan-history.js`
- Modify: `templates/index.html`（删 197/217/220/221 四行，按内容定位）
- Modify: `static/js/store.js:164`
- Rewrite: `tests/test_history_legacy_preserved.py` → `tests/test_history_legacy_retired.py`

- [ ] **Step 1: 反转守护测试——断言旧页文件已退役**

```bash
git rm tests/test_history_legacy_preserved.py
```

新建 `tests/test_history_legacy_retired.py`：

```python
"""Phase 4c 守护：旧 SPA 货号历史页已退役（与原 test_history_legacy_preserved 反向）。

货号历史已全量迁 Vue /ui/history（含批次记录），旧 Alpine 页已删。
本测试防止误把旧页文件 / nav 条目重新加回；并正向锁定 /scan_history 蓝图必须保留。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_old_spa_history_nav_entry_removed():
    store_js = (ROOT / "static" / "js" / "store.js").read_text(encoding="utf-8")
    assert '{ id: "history"' not in store_js, "旧 SPA 侧栏 history 条目应已删（4c）"


def test_old_spa_history_files_removed():
    for rel in (
        "templates/partials/_page_history.html",
        "static/js/history.js",
        "static/js/index-recent-changes.js",
        "static/js/index-scan-history.js",
    ):
        assert not (ROOT / rel).exists(), f"{rel} 应已删除（4c）"


def test_index_html_no_legacy_history_refs():
    index_html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    for token in (
        "_page_history.html",
        "js/history.js",
        "index-recent-changes.js",
        "index-scan-history.js",
    ):
        assert token not in index_html, f"index.html 不应再引用 {token}（4c）"


def test_scan_history_blueprint_preserved():
    """反向保险：/scan_history 蓝图必须保留（新页 + 标签页共用二进制下载，绝不可删）。"""
    assert (ROOT / "app" / "routes" / "scan_history.py").exists(), (
        "/scan_history 蓝图必须保留——新 Vue 页与标签处理页都依赖二进制下载"
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_history_legacy_retired.py -q`
Expected: FAIL —— 旧文件还在 / store.js 还有条目 / index.html 还有引用（`test_scan_history_blueprint_preserved` 已 PASS）。

- [ ] **Step 3: 删旧页 4 个文件**

```bash
git rm templates/partials/_page_history.html static/js/history.js static/js/index-recent-changes.js static/js/index-scan-history.js
```

- [ ] **Step 4: 从 index.html 删 include + 3 个 script**

编辑 `templates/index.html`，按内容删除这 4 行：

```html
{% include 'partials/_page_history.html' %}
```
```html
<script type="module" src="{{ url_for('static', filename='js/history.js') }}"></script>
```
```html
<script type="module" src="{{ url_for('static', filename='js/index-recent-changes.js') }}"></script>
```
```html
<script type="module" src="{{ url_for('static', filename='js/index-scan-history.js') }}"></script>
```

- [ ] **Step 5: 从 store.js 删 history pages 条目**

编辑 `static/js/store.js`，删除第 164 行（仅此行，不动其余条目与缩进）：

```js
      { id: "history",           label: "货号历史",   icon: "history",    code: "05", shortcut: "5" },
```

- [ ] **Step 6: 跑守护测试 + 全量后端确认通过**

Run: `pytest tests/test_history_legacy_retired.py -q && pytest tests/ -q`
Expected: PASS（守护全绿 + 整套后端无回归；此时旧 SPA 调用方已删，`/recent_changes` 蓝图仍在但已无人调，下个任务删）。

- [ ] **Step 7: Commit（显式列文件，勿用 -A —— 工作树有未跟踪论文/截图）**

```bash
git add templates/index.html static/js/store.js tests/test_history_legacy_retired.py
git commit -m "refactor(history): 退役旧 SPA 货号历史页 + nav 条目（4c）"
```

（`git rm` 的删除已在 Step 1/3 暂存；`git status` 核对暂存区只含本任务文件 + 删除项，无论文/截图。）

---

### Task 4: 删除旧 `recent_changes` HTTP 蓝图（D8/D9/D10）+ URL map 行为契约（反向守护）

**Files:**
- Delete: `app/routes/recent_changes.py`
- Modify: `app/routes/__init__.py:26,40`
- Delete: `tests/test_recent_changes_routes.py`
- Modify: `tests/test_history_legacy_retired.py`（追加 URL map 行为测试）

- [ ] **Step 1: 追加失败的 URL map 行为测试**

往 `tests/test_history_legacy_retired.py` 末尾追加（顶部加 `from server import create_app`）：

```python
def _rules():
    app = create_app(seed_auth=False, prewarm=False)
    return [r.rule for r in app.url_map.iter_rules()]


def test_recent_changes_http_routes_unregistered():
    rules = _rules()
    assert not any(r.startswith("/recent_changes") for r in rules), (
        "旧 /recent_changes/* HTTP 路由应已注销（4c）"
    )


def test_new_and_scan_routes_still_registered():
    rules = _rules()
    assert any(r.startswith("/api/history/recent-changes") for r in rules), (
        "新 /api/history/recent-changes/* 必须仍在"
    )
    assert any(r.startswith("/scan_history") for r in rules), (
        "/scan_history/* 必须仍在（新页 + 标签页下载）"
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_history_legacy_retired.py::test_recent_changes_http_routes_unregistered -q`
Expected: FAIL —— 蓝图仍注册，`/recent_changes/imports` 等在 url_map 中。
（`test_new_and_scan_routes_still_registered` 应已 PASS。）

- [ ] **Step 3: 确认无残留 HTTP 调用方（限定非测试代码目录）**

Run: `git grep -n "/recent_changes" -- app static templates frontend`
Expected: **仅** `app/routes/recent_changes.py`（待删）。
（**排除 `tests`**：新追加的 `test_history_legacy_retired.py` 守护断言里含 `"/recent_changes"` 字符串字面量，会自命中；调用方检查只看非测试源。旧 `static/js/index-recent-changes.js` 已在 Task 3 删除；`app/routes/history.py` 用的是 `/api/history/recent-changes` 连字符不匹配；docs/ 因 `--` 限定被排除。）

- [ ] **Step 4: 删蓝图文件 + 旧路由测试 + 注销注册**

```bash
git rm app/routes/recent_changes.py tests/test_recent_changes_routes.py
```

编辑 `app/routes/__init__.py`：删第 26 行 import 与第 40 行注册：

```python
from app.routes.recent_changes import bp as recent_changes_bp
```
```python
    app.register_blueprint(recent_changes_bp)
```

- [ ] **Step 5: 跑测试确认通过 + 全量后端无回归**

Run: `pytest tests/test_history_legacy_retired.py -q && pytest tests/ -q`
Expected: PASS（无 `ModuleNotFoundError`/`NameError`；service 测试 + 新 `/api/history/recent-changes` 测试仍全绿）。

- [ ] **Step 6: ruff + commit**

Run: `ruff check app/routes/__init__.py tests/test_history_legacy_retired.py && ruff format --check app/routes/__init__.py tests/test_history_legacy_retired.py`
Expected: clean。

```bash
git add app/routes/__init__.py tests/test_history_legacy_retired.py
git commit -m "refactor(history): 删除旧 recent_changes HTTP 蓝图 + URL map 契约守护（4c）"
```

---

### Task 5: 全量验证（前后端 + 类型漂移 + 浏览器人工验收）

**Files:** 无（仅验证）

- [ ] **Step 1: 后端双腿**

Run: `pytest tests/ -q` 然后 `./test.ps1`
Expected: 两者全绿（sqlite + 本地 PG/xdist）。

- [ ] **Step 2: TS 类型零漂移**

Run: `python tools/gen_ts_types.py --check`
Expected: 退出码 0（本期未动 schema，无漂移）。非 0 说明误改 schema，回查。

- [ ] **Step 3: 前端单测 + typecheck + build**

Run: `cd frontend && npm run test:unit && npx vue-tsc --noEmit && npm run build`
Expected: 全绿。

- [ ] **Step 4: ruff 全量**

Run: `ruff check . && ruff format --check .`
Expected: clean。

- [ ] **Step 5: 浏览器人工验收**

`./dev.ps1 -Frontend` 起本地栈（admin/admin 登录），逐项确认：
- `/ui/history` 命中态：深链「查看完整分析（旧版）」已消失；查询 / 概况-深度切换 / 5 折叠卡（SLA·PUR·RST·TML·HIS）/ 批次记录两子-tab（最近改动 + 扫描批次，扫描批次下载 CSV/ZIP 可点）全部正常。
- 浏览器访问 `/?page=history`：被 302 跳到 `/ui/history`（地址栏变化，无闪屏）。
- 标签处理页 `/?page=main`：「下载结果」仍可用（验证 `/scan_history/batches/<id>/download/zip` 未被波及）。

- [ ] **Step 6: 收尾**

确认所有 commit 在 feat 分支（非直接 main）。准备 squash PR 回 main（参照既有 §11 迁移流程；CI 双矩阵须四绿后合）。

---

### Task 6: 货号下钻深链（Vue `?q=` + 302 透传 q + 重指向 restock/sales-analytics）

最终全分支审查发现的回归补救：删 history.js 后 `restock.js`（live 页）下钻 `window.historySearch` 成 no-op。给 Vue 页加 `?q=` 深链并自动搜索，再重指向下钻。

**Files:**
- Modify: `frontend/src/pages/history/HistoryPage.vue`（import useRoute + watch route.query.q）
- Modify: `app/routes/pages_tasks.py`（302 透传 q）
- Modify: `static/js/restock.js`（`.rs-bc-link` handler）
- Modify: `static/js/sales-analytics.js`（同款，dead 但一致清理）
- Test: `frontend/src/pages/history/HistoryPage.test.ts`（deep-link）+ `tests/test_history_legacy_redirect.py`（302 透传 q）

- [ ] **Step 1: 写失败测试（前端 deep-link + 后端 302 透传 q）**

后端 `tests/test_history_legacy_redirect.py` 追加（已登录夹具 `real_app`/`_login` 复用）：

```python
def test_page_history_redirect_preserves_q(real_app):
    client = real_app.test_client()
    _login(real_app, client)
    resp = client.get("/?page=history&q=8299979002791")
    assert resp.status_code == 302
    loc = urlparse(resp.headers["Location"])
    assert loc.path == "/ui/history"
    assert parse_qs(loc.query).get("q") == ["8299979002791"]


def test_page_history_redirect_urlencodes_q(real_app):
    client = real_app.test_client()
    _login(real_app, client)
    resp = client.get("/?page=history&q=" + "a b/c")  # 空格 + 斜杠需编码
    assert resp.status_code == 302
    loc = urlparse(resp.headers["Location"])
    assert loc.path == "/ui/history"
    assert parse_qs(loc.query).get("q") == ["a b/c"]  # 解码后还原
```

前端 `HistoryPage.test.ts` 追加 deep-link 测试，**必须用 reactive route fixture**（普通对象只能覆盖首次挂载，触发不了运行时 query 变化）。推荐模式：

```ts
import { reactive } from "vue";
let routeRef: { query: Record<string, unknown> };
vi.mock("vue-router", () => ({ useRoute: () => routeRef }));
// 在 imports 之后初始化（factory 闭包惰性读取，mount 时已赋值）：
routeRef = reactive({ query: {} });
// reset() 里：routeRef.query = {};
```

覆盖 4 场景：
- `?q=<bc>` 首次挂载（immediate）→ 调 `store.load(<bc>)`（含 "deep" 关键字）。
- 无 `q` 挂载 → 不调 `store.load`。
- **A→B 运行时**：挂载 q=A，改 `routeRef.query = { q: "B" }` + `await flushPromises()` → `store.load` 以 "B" 再次被调。
- **A→空运行时**：挂载 q=A，改 `routeRef.query = {}` + `await flushPromises()` → 输入框 `q` 清空（断言 input value 为空）且 `store.reset`（四 store 之一）被调。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_history_legacy_redirect.py -q` → 新两条 FAIL（当前 302 丢弃 q）。
Run: `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts -t "deep"` → deep-link 测试 FAIL。

- [ ] **Step 3: 实现 302 透传 q**

`app/routes/pages_tasks.py` index()：

```python
@bp.get("/")
def index():
    # Phase 4c：旧书签 /?page=history → Vue 页（保留 q 深链；其余 page=* 仍交客户端 SPA）
    if request.args.get("page") == "history":
        q = request.args.get("q")
        if q:
            from urllib.parse import quote

            return redirect(f"/ui/history?q={quote(q, safe='')}", code=302)
        return redirect("/ui/history", code=302)
    return render_template(
        "index.html",
        enable_transfer=CONFIG.enable_transfer,
        is_admin=(getattr(current_user, "role", None) == "admin"),
    )
```

- [ ] **Step 4: 实现 Vue `?q=` 深链**

`HistoryPage.vue` `<script setup>`：import 加 `import { useRoute } from "vue-router";`，在 `runSearch` 定义之后加：

```ts
const route = useRoute();
watch(
  () => route.query.q,
  (val) => {
    const query = typeof val === "string" ? val.trim() : "";
    if (query) {
      activeTab.value = "search";
      q.value = query;
      runSearch(query);
    } else {
      doReset(); // 空/缺省 q：清输入 + reset 四 store（避免从 ?q=A 回到无 q 时残留）
    }
  },
  { immediate: true },
);
```

`doReset` 是 hoisted 函数声明（文件后段定义），immediate 同步首跑也可引用。空 q 首次挂载调 `doReset` 幂等无害（store 本就空）。

- [ ] **Step 5: 重指向 restock.js + sales-analytics.js**

`static/js/restock.js` 的 `.rs-bc-link` handler（约 1044-1052）改为：

```js
    for (const link of tbody.querySelectorAll(".rs-bc-link")) {
      link.addEventListener("click", (e) => {
        e.stopPropagation();
        location.href = "/ui/history?q=" + encodeURIComponent(link.dataset.bc);
      });
    }
```

`static/js/sales-analytics.js`（约 144-152）同款重指向（删 `window.historySearch` 死块）。

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/test_history_legacy_redirect.py -q`（全绿）
Run: `cd frontend && npx vitest run src/pages/history/HistoryPage.test.ts && npx vue-tsc --noEmit`（全绿 + typecheck）

- [ ] **Step 7: ruff + commit**

Run: `python -m ruff check app/routes/pages_tasks.py tests/test_history_legacy_redirect.py && python -m ruff format --check app/routes/pages_tasks.py tests/test_history_legacy_redirect.py`

```bash
git add frontend/src/pages/history/HistoryPage.vue frontend/src/pages/history/HistoryPage.test.ts app/routes/pages_tasks.py tests/test_history_legacy_redirect.py static/js/restock.js static/js/sales-analytics.js
git commit -m "feat(history): 货号下钻深链 /ui/history?q= + 302 透传 q + 重指向 restock（4c review）"
```

- [ ] **Step 8: 重跑 Task 5 全量验证**（ruff 全量 / gen_ts_types --check / 前端三连 / 后端 sqlite）。

## Self-Review

- **Spec coverage**：D1-D12 + A1 + T1/T2 全部映射——Task 1（D11/D12/T2）、Task 2（A1 + redirect 测试）、Task 3（D1-D7/T1）、Task 4（D8/D9/D10 + URL map 契约）；保留项由 Task 3 `test_scan_history_blueprint_preserved` + Task 4 `test_new_and_scan_routes_still_registered` + Task 4 Step 3 scoped grep 三重守护；验证 = Task 5。
- **原子性（审查阻断 1）**：旧 SPA 调用方（Task 3）先于蓝图删除（Task 4），无「页在调、端点 404」中间提交；302 兜底（Task 2）先于删页。
- **行为守护（审查阻断 2）**：Task 4 URL map 契约测试断言 `/recent_changes` 注销 + 新路由/`/scan_history` 仍在，覆盖「从别处重新注册」。
- **grep 失真（审查阻断 3）**：Task 4 Step 3 限定 `-- app static templates frontend tests`，排除 docs。
- **git add 范围（审查阻断 4）**：Task 3 Step 7 显式列文件 + `git status` 核对，杜绝未跟踪论文/截图入提交。
- **类型一致**：未引入新类型；`test_history_legacy_retired.py` 在 Task 3 建、Task 4 追加 URL map 函数，自洽。
- **认证夹具（审查二轮阻断 1）**：302 测试改用 seed admin + `session_transaction`（照搬 `test_index_render_smoke.py`），不再用失效的 `LOGIN_DISABLED`；Location 用 `urlparse(...).path == "/ui/history"` 精确断言；补未登录→`/login`(next 保留)→登录→Vue 完整回跳测试。
- **grep 自命中（审查二轮阻断 2）**：Task 4 调用方检查限定 `-- app static templates frontend`（排除 tests，避免守护测试里的 `"/recent_changes"` 字面量自命中），Expected 收敛为仅 `app/routes/recent_changes.py`。
