# 抓取失败告警 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给数据新鲜度加一个独立的"抓取成败"信号——抓取器成功心跳写 SystemSetting，freshness 据此区分"静默周"与"抓取挂"，缺心跳超 8 天页面红条告警。

**Architecture:** 抓取器(跨仓,用户自接)成功后 POST `/analytics/scrape/heartbeat`(token-only) → 服务端写 `SystemSetting(scrape:last_success_at)`=now(UTC) → `get_data_freshness()` 读该 key 增 3 字段(`last_scrape_success_at/scrape_days_since/scrape_stale`,阈值8天,只按日期算) → 首页红条按 5 级优先级显示。admin.js `renderRecentImports` 字段错配作独立 opportunistic bugfix。

**Tech Stack:** Flask + SQLAlchemy(SystemSetting key-value) + Alpine.js(红条) + pytest。复用既有 `@require_upload_token` 装饰器与 `stockpile_db._session()`。

**Spec:** `docs/superpowers/specs/2026-06-06-scrape-failure-alert-design.md`

---

## File Structure

- `app/services/analytics/freshness.py` — 增 `HEARTBEAT_KEY` / `_SCRAPE_STALE_DAYS` 常量 + `get_data_freshness()` 读心跳并增 3 字段。
- `app/routes/analytics.py` — 新增 `POST /analytics/scrape/heartbeat` 端点(`@require_upload_token`)。
- `tests/test_data_freshness.py` — freshness scrape 字段四态测试。
- `tests/test_routes_analytics.py` — 端点 happy-path(写库+200,bare blueprint+self.auth)。
- `tests/test_cron_forecast_auth.py` — 端点鉴权契约(302/401/500,full-app)。
- `templates/index.html:138-145` — 红条 5 级优先级(Alpine getter)。
- `static/js/admin.js:203-225` — `renderRecentImports` 字段修复(独立 commit)。

---

## Task 1: freshness 增 scrape 字段

**Files:**
- Modify: `app/services/analytics/freshness.py`
- Test: `tests/test_data_freshness.py`

- [ ] **Step 1: Write the failing tests**

在 `tests/test_data_freshness.py` 的 `_Base` 类加心跳写入 helper，并加一个新测试类。`_Base` 现有 `_add_event`，在其后追加：

```python
    def _set_heartbeat(self, iso: str) -> None:
        from app.models import SystemSetting

        with stockpile_db._session() as s:
            row = s.get(SystemSetting, "scrape:last_success_at")
            if row:
                row.value = iso
            else:
                s.add(SystemSetting(key="scrape:last_success_at", value=iso, updated_by="test"))
            s.commit()
```

文件末尾(`if __name__` 之前)加测试类：

```python
class TestScrapeHeartbeatFreshness(_Base):
    AS_OF = date(2026, 6, 10)

    def test_no_heartbeat_not_stale_none(self) -> None:
        """空心跳: 字段为 None, 不报 scrape_stale。"""
        from app.services.analytics import get_data_freshness

        r = get_data_freshness(as_of=self.AS_OF)
        self.assertIsNone(r["last_scrape_success_at"])
        self.assertIsNone(r["scrape_days_since"])
        self.assertFalse(r["scrape_stale"])

    def test_fresh_heartbeat_today_not_stale(self) -> None:
        from app.services.analytics import get_data_freshness

        self._set_heartbeat("2026-06-10T03:00:00+00:00")
        r = get_data_freshness(as_of=self.AS_OF)
        self.assertEqual(r["last_scrape_success_at"], "2026-06-10T03:00:00+00:00")
        self.assertEqual(r["scrape_days_since"], 0)
        self.assertFalse(r["scrape_stale"])

    def test_boundary_8_days_not_stale(self) -> None:
        """恰好 8 天 → 不 stale (阈值是 > 8, 非 >=)。"""
        from app.services.analytics import get_data_freshness

        self._set_heartbeat("2026-06-02T03:00:00+00:00")  # 8 天前
        r = get_data_freshness(as_of=self.AS_OF)
        self.assertEqual(r["scrape_days_since"], 8)
        self.assertFalse(r["scrape_stale"])

    def test_9_days_is_stale(self) -> None:
        from app.services.analytics import get_data_freshness

        self._set_heartbeat("2026-06-01T03:00:00+00:00")  # 9 天前
        r = get_data_freshness(as_of=self.AS_OF)
        self.assertEqual(r["scrape_days_since"], 9)
        self.assertTrue(r["scrape_stale"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_data_freshness.py::TestScrapeHeartbeatFreshness -v`
Expected: FAIL with `KeyError: 'last_scrape_success_at'`(字段还不存在)。

- [ ] **Step 3: Implement freshness scrape fields**

改 `app/services/analytics/freshness.py`。import 加 `SystemSetting`，加常量，改 `get_data_freshness`：

```python
from app.models import InventoryEvent, SystemSetting
```

常量区(`_DATA_STALE_DAYS = 9` 旁)加：

```python
# 抓取成功心跳: 抓取器每周成功跑完打一次 (写 SystemSetting)。距上次心跳 > 8 天
# (周抓 7 + 1 缓冲, 比数据龄 9 天更早暴露) → 判定抓取可能中断。
_SCRAPE_STALE_DAYS = 8
HEARTBEAT_KEY = "scrape:last_success_at"
```

`get_data_freshness` 改为(读心跳 + 返回增 3 字段)：

```python
def get_data_freshness(as_of: date | None = None) -> dict[str, Any]:
    """返回数据新鲜度: 数据龄(imported_at) + 抓取心跳(scrape:last_success_at)。

    {last_import_at, last_import_date, days_since, stale,
     last_scrape_success_at, scrape_days_since, scrape_stale}
    空库 / 空心跳 → 对应字段 None + 对应 stale=False (新系统/本地不误报)。
    """
    as_of = as_of or _today()
    with stockpile_db._session() as session:
        last = session.execute(select(func.max(InventoryEvent.imported_at))).scalar()
        hb = session.get(SystemSetting, HEARTBEAT_KEY)

    hb_val = hb.value if hb else None
    if hb_val:
        # 只按日期算 (UTC ISO 取前 10 字符 → date), 避免时区细节影响 UI。
        scrape_date = _parse_date(hb_val)
        scrape_days_since: int | None = (as_of - scrape_date).days
        scrape_stale = scrape_days_since > _SCRAPE_STALE_DAYS
    else:
        scrape_days_since = None
        scrape_stale = False

    if not last:
        return {
            "last_import_at": None,
            "last_import_date": None,
            "days_since": None,
            "stale": False,
            "last_scrape_success_at": hb_val,
            "scrape_days_since": scrape_days_since,
            "scrape_stale": scrape_stale,
        }
    last_date = _parse_date(str(last))
    days = (as_of - last_date).days
    return {
        "last_import_at": str(last),
        "last_import_date": last_date.isoformat(),
        "days_since": days,
        "stale": days > _DATA_STALE_DAYS,
        "last_scrape_success_at": hb_val,
        "scrape_days_since": scrape_days_since,
        "scrape_stale": scrape_stale,
    }
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_data_freshness.py -v`
Expected: PASS (新 4 个 + 既有全过)。

- [ ] **Step 5: Commit**

```bash
git add app/services/analytics/freshness.py tests/test_data_freshness.py
git commit -m "feat(freshness): get_data_freshness 增抓取心跳 3 字段(scrape_stale 阈值8天)"
```

---

## Task 2: 心跳端点 POST /analytics/scrape/heartbeat

**Files:**
- Modify: `app/routes/analytics.py`
- Test: `tests/test_routes_analytics.py`(happy-path 写库) + `tests/test_cron_forecast_auth.py`(鉴权契约)

- [ ] **Step 1: Write the failing happy-path test (bare blueprint)**

在 `tests/test_routes_analytics.py` 的 `BacktestRoutesTests` 类(已有 setUp 注入 `self.auth` token)内加：

```python
    def test_scrape_heartbeat_writes_system_setting(self) -> None:
        """POST /scrape/heartbeat: 正确 token -> 200 且写 SystemSetting。"""
        from app.models import SystemSetting

        resp = self.client.post("/analytics/scrape/heartbeat", headers=self.auth)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["last_scrape_success_at"].endswith("+00:00"))
        with stockpile_db._session() as s:
            row = s.get(SystemSetting, "scrape:last_success_at")
        self.assertIsNotNone(row)
        self.assertEqual(row.value, body["last_scrape_success_at"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_routes_analytics.py::BacktestRoutesTests::test_scrape_heartbeat_writes_system_setting -v`
Expected: FAIL with 404(端点不存在)。

- [ ] **Step 3: Implement endpoint**

在 `app/routes/analytics.py` 的 `backtest_refresh` 之后(或 `forecast_refresh` 附近)加：

```python
@bp.post("/scrape/heartbeat")
@require_upload_token
def scrape_heartbeat():
    """抓取器成功心跳: 写 SystemSetting(scrape:last_success_at)=now(UTC ISO)。

    无 body (供抓取器 run_weekly 成功尾部 curl 调, token-only)。区分"静默周"
    (心跳新鲜+数据没动) 与"抓取挂"(心跳过期)。返回 {ok, last_scrape_success_at}。
    """
    from datetime import datetime, timezone

    from app.models import SystemSetting
    from app.services.analytics.freshness import HEARTBEAT_KEY

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with stockpile_db._session() as session:
        row = session.get(SystemSetting, HEARTBEAT_KEY)
        if row:
            row.value = ts
            row.updated_by = "scraper"
        else:
            session.add(SystemSetting(key=HEARTBEAT_KEY, value=ts, updated_by="scraper"))
        session.commit()
    return jsonify({"ok": True, "last_scrape_success_at": ts})
```

- [ ] **Step 4: Run to verify happy-path passes**

Run: `python -m pytest tests/test_routes_analytics.py::BacktestRoutesTests::test_scrape_heartbeat_writes_system_setting -v`
Expected: PASS。

- [ ] **Step 5: Write the failing auth-contract tests (full-app)**

在 `tests/test_cron_forecast_auth.py` 末尾加(`os` 已 import, `_client()` 已有)：

```python
def test_scrape_heartbeat_without_token_redirected_to_login():
    resp = _client().post("/analytics/scrape/heartbeat")

    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_scrape_heartbeat_wrong_token_rejected():
    os.environ["UPLOAD_TOKEN"] = "secret_token_abc"
    try:
        resp = _client().post(
            "/analytics/scrape/heartbeat",
            headers={"X-Upload-Token": "wrong"},
        )
    finally:
        os.environ.pop("UPLOAD_TOKEN", None)

    assert resp.status_code == 401
    assert resp.get_json()["ok"] is False


def test_scrape_heartbeat_server_unconfigured_is_500():
    os.environ.pop("UPLOAD_TOKEN", None)
    resp = _client().post(
        "/analytics/scrape/heartbeat",
        headers={"X-Upload-Token": "whatever"},
    )

    assert resp.status_code == 500
    assert resp.get_json()["ok"] is False
```

- [ ] **Step 6: Run auth-contract tests**

Run: `python -m pytest tests/test_cron_forecast_auth.py -v -k scrape_heartbeat`
Expected: PASS(3 个: 302 / 401 / 500)。

- [ ] **Step 7: Commit**

```bash
git add app/routes/analytics.py tests/test_routes_analytics.py tests/test_cron_forecast_auth.py
git commit -m "feat(scrape): POST /analytics/scrape/heartbeat 成功心跳端点(token-only)"
```

---

## Task 3: 红条 5 级优先级

**Files:**
- Modify: `templates/index.html:138-145`

> 注: Alpine 客户端逻辑无单测覆盖，验证靠模板渲染无报错 + 本地浏览器人工核对。

- [ ] **Step 1: 替换红条块**

把 `templates/index.html` 第 138-145 行(`<div class="header-freshness" ...>` 整块)替换为：

```html
      <div class="header-freshness" x-data="{ f: null,
             get fr() {
               const f = this.f; if (!f) return null;
               if (f.scrape_stale) return { red: true, text: '⚠ 抓取可能中断（距上次成功抓取 ' + f.scrape_days_since + ' 天）' };
               if (f.stale) return { red: true, text: '⚠ 数据截止 ' + f.last_import_date + ' · 距今 ' + f.days_since + ' 天（疑似停更，请检查抓取脚本）' };
               if (f.last_import_date) return { red: false, text: '数据截止 ' + f.last_import_date + ' · 距今 ' + f.days_since + ' 天' };
               if (f.last_scrape_success_at) return { red: false, text: '抓取器最近成功 ' + f.last_scrape_success_at };
               return null;
             } }"
           x-init="fetch('/analytics/data-freshness').then(r => r.json()).then(d => { if (d && d.ok) f = d; }).catch(() => {})"
           x-show="f && (f.scrape_stale || f.stale || f.last_import_date || f.last_scrape_success_at)"
           :style="`font-size:var(--fs-sm);margin-right:12px;${fr && fr.red ? 'color:var(--error);font-weight:600' : 'color:var(--ink-3)'}`"
           :title="f && f.last_import_at ? ('最近灌数时间 ' + f.last_import_at) : ''">
        <span x-text="fr ? fr.text : ''"></span>
      </div>
```

- [ ] **Step 2: 渲染无报错验证**

Run:
```bash
FLASK_SECRET_KEY=dummy_harness_key python -c "from server import create_app; a=create_app(seed_auth=False, prewarm=False);
import flask
with a.test_request_context('/'):
    h=flask.render_template('index.html', is_admin=True, enable_transfer=True)
    assert 'header-freshness' in h and 'scrape_stale' in h
    print('OK render, len', len(h))"
```
Expected: `OK render` (模板无 Jinja 语法错误且新逻辑已渲染)。

- [ ] **Step 3: 本地浏览器人工核对(4 态)**

启 `python server.py`(或 dev.ps1)，登录后开首页。用以下方式造数据看红条：
- 无心跳无数据 → 红条隐藏。
- `curl -X POST -H "X-Upload-Token: $TOKEN" localhost:5000/analytics/scrape/heartbeat` → 心跳新鲜 → 中性"抓取器最近成功"(若无 import 数据)或正常"数据截止"。
- 手动改 SystemSetting `scrape:last_success_at` 为 9 天前 ISO → 红色"抓取可能中断（距上次成功抓取 9 天）"。
- 既有数据 stale 路径不回归(red + "疑似停更")。

- [ ] **Step 4: Commit**

```bash
git add templates/index.html
git commit -m "feat(ui): 首页新鲜度红条改 5 级优先级(scrape_stale 优先)"
```

---

## Task 4: admin.js renderRecentImports 字段修复 (opportunistic bugfix, 独立 commit)

**Files:**
- Modify: `static/js/admin.js:203-225`

> 注: 与心跳不同逻辑链，独立 commit，不计入心跳验收。无 JS 单测，靠浏览器/e2e 验证。

- [ ] **Step 1: 修字段映射**

`static/js/admin.js` 的 `renderRecentImports` 内，把 `const items = r.items || [];` 改为 `const items = r.imports || [];`，并把行渲染改为用端点真字段(`event_type`/`error_count`/`total_rows`/`ok_count`/`filename`)：

```javascript
    const items = r.imports || [];
    if (!items.length) { tbody.innerHTML = '<tr><td colspan="5" class="pnl-empty">暂无 import 记录</td></tr>'; return; }
    tbody.innerHTML = items.map((it) => {
      const ok = (it.error_count ?? 0) === 0;
      const ts = (it.imported_at || "").slice(0, 16).replace("T", " ");
      return `<tr>
        <td class="mono" style="font-size:var(--fs-xs);color:var(--ink-2)">${ts}</td>
        <td class="mono" style="font-size:var(--fs-xs)">${INV_TYPE_CN[it.event_type] || it.event_type || "—"}</td>
        <td style="color:${ok ? 'var(--success)' : 'var(--error)'};font-weight:600">${ok ? '✓' : '✗'} ${(it.ok_count ?? 0).toLocaleString()}/${(it.total_rows ?? 0).toLocaleString()}</td>
        <td class="r mono" style="font-size:var(--fs-sm)">${(it.total_rows ?? 0).toLocaleString()}</td>
        <td class="mono" style="font-size:var(--fs-xs);color:var(--ink-2)">${esc(it.filename || '')}</td>
      </tr>`;
    }).join("");
```

- [ ] **Step 2: 浏览器人工核对**

启本地 server，登录 admin，开系统管理页，确认"最近导入"表格能渲染出行(之前永远空)，状态 ✓/✗ 随 error_count 正确，行数显示 total_rows。

- [ ] **Step 3: Commit**

```bash
git add static/js/admin.js
git commit -m "fix(admin): renderRecentImports 字段对齐 /inventory/imports(r.imports + 真字段)"
```

---

## 收尾验证

- [ ] 全量回归: `python -m pytest tests/ -q` → 应 1077 + 8 新(Task1 四 freshness + Task2 一 happy + 三 auth) = **1085 passed**。
- [ ] 抓取器侧文档: 在 PR 描述或 README 注明抓取器 run_weekly 成功尾部需加 `curl -fsS -X POST -H "X-Upload-Token: $TOKEN" <host>/analytics/scrape/heartbeat`。
