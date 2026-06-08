# 补货页 skip 抑制（决策反馈回流）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 标「不进」的 SKU 默认隐藏 14 天（到期或新进货自动解除），把已写入 `restock_decisions` 的 skipped 决策读回来影响下一次补货列表展示。

**Architecture:** 后端新增 `list_suppressed` 纯查询 + `GET /restock/decisions/suppressed` 端点，按"最近一条决策是 skipped 且在 14 天内且无后续新进货"算出抑制集；前端 `load()` 拉进 `state.suppressed`，`_filterPredicate` 默认隐藏、新增「已跳过」band 翻出，标「不进」时 await POST 成功后乐观隐藏。评分算法 `restock_calc.py` 与 DB schema 全不动。

**Tech Stack:** Python 3.12 + SQLAlchemy 2.x（后端 service/route）、pytest（后端 TDD）、Vanilla JS（restock.js 手写 render）、Flask 模板 partial、Tailwind v4 + 自定义 components.css。

**spec:** `docs/superpowers/specs/2026-06-08-restock-skip-suppression-design.md`

**测试策略:** 后端 `list_suppressed` 走 TDD（pytest，6 用例覆盖到期/进货解除/最近是 ordered/同日进货/多条取最近），可执行验证。前端无 JS 单测框架 → 本地 `dev.ps1` + 合成数据人工/Playwright 走查。最后全量 `pytest tests/` 确认无回归。

---

## 文件结构

| 文件 | 改动 |
|---|---|
| `app/services/restock_decisions.py` | 加常量 `SKIP_SUPPRESS_DAYS=14` + 函数 `list_suppressed(session)`；import 加 `date`、`func`、`InventoryEvent` |
| `app/routes/restock.py` | 加 `GET /restock/decisions/suppressed` 端点 |
| `tests/test_restock_decisions.py` | 加 `SuppressedTests` 类（6 用例）+ 路由 smoke |
| `static/js/restock.js` | `state.suppressed`+`SKIP_SUPPRESS_DAYS`；`load()` 拉 suppressed；`_filterPredicate` 隐藏/已跳过 band；renderRow skipped tag；`markSelectedSkipped`/`markSingleSkipped` 改 await POST 成功后乐观隐藏；`recordDecisionsBatch` 返回 ok |
| `templates/partials/_page_restock.html` | band 行加「已跳过」chip |
| `static/css/components.css` | 加 `.rs-tag--skip` 样式 |

---

## Task 1: 后端 `list_suppressed` 服务函数（TDD）

**Files:**
- Modify: `app/services/restock_decisions.py`
- Test: `tests/test_restock_decisions.py`

- [ ] **Step 1: 写失败测试**

`tests/test_restock_decisions.py` 第 9 行
```python
from app.models import RestockDecision
```
改成
```python
from app.models import InventoryEvent, RestockDecision
```
然后在文件末尾 `if __name__ == "__main__":` 之前插入：

```python
class SuppressedTests(_Base):
    """list_suppressed: 最近一条是 skipped 且 14 天内且无后续新进货 → 抑制."""

    @staticmethod
    def _days_ago(n: int) -> str:
        from datetime import UTC, datetime, timedelta

        return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _date_ago(n: int) -> str:
        from datetime import UTC, datetime, timedelta

        return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")

    def _add_decision(self, s, barcode, decision, days_ago, reason=None):
        s.add(
            RestockDecision(
                barcode=barcode,
                decision=decision,
                decided_at=self._days_ago(days_ago),
                reason=reason,
                urgency_score=80,
            )
        )

    def _add_purchase(self, s, barcode, days_ago):
        s.add(
            InventoryEvent(
                event_at=self._date_ago(days_ago),
                event_type="purchase",
                product_barcode=barcode,
                qty=10,
            )
        )

    def test_recent_skip_within_window_no_purchase_is_suppressed(self):
        with stockpile_db._session() as s:
            self._add_decision(s, "B1", "skipped", days_ago=5, reason="供应商断货")
            s.commit()
        with stockpile_db._session() as s:
            sup = svc.list_suppressed(s)
        assert "B1" in sup
        assert sup["B1"]["reason"] == "供应商断货"
        assert sup["B1"]["days_left"] == svc.SKIP_SUPPRESS_DAYS - 5

    def test_skip_older_than_window_not_suppressed(self):
        with stockpile_db._session() as s:
            self._add_decision(s, "B2", "skipped", days_ago=15)
            s.commit()
        with stockpile_db._session() as s:
            sup = svc.list_suppressed(s)
        assert "B2" not in sup

    def test_latest_decision_ordered_not_suppressed(self):
        with stockpile_db._session() as s:
            self._add_decision(s, "B3", "skipped", days_ago=6)
            self._add_decision(s, "B3", "ordered", days_ago=2)  # 更近的是 ordered
            s.commit()
        with stockpile_db._session() as s:
            sup = svc.list_suppressed(s)
        assert "B3" not in sup

    def test_purchase_after_skip_releases(self):
        with stockpile_db._session() as s:
            self._add_decision(s, "B4", "skipped", days_ago=6)
            self._add_purchase(s, "B4", days_ago=2)  # 进货晚于跳过日
            s.commit()
        with stockpile_db._session() as s:
            sup = svc.list_suppressed(s)
        assert "B4" not in sup

    def test_same_day_purchase_still_suppressed(self):
        with stockpile_db._session() as s:
            self._add_decision(s, "B5", "skipped", days_ago=6)
            self._add_purchase(s, "B5", days_ago=6)  # 同日进货, 不算晚于
            s.commit()
        with stockpile_db._session() as s:
            sup = svc.list_suppressed(s)
        assert "B5" in sup

    def test_multiple_skips_uses_latest(self):
        with stockpile_db._session() as s:
            self._add_decision(s, "B6", "skipped", days_ago=10, reason="旧原因")
            self._add_decision(s, "B6", "skipped", days_ago=3, reason="新原因")
            s.commit()
        with stockpile_db._session() as s:
            sup = svc.list_suppressed(s)
        assert sup["B6"]["reason"] == "新原因"
        assert sup["B6"]["days_left"] == svc.SKIP_SUPPRESS_DAYS - 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_restock_decisions.py::SuppressedTests -v`
Expected: FAIL —`AttributeError: module 'app.services.restock_decisions' has no attribute 'list_suppressed'`（及 `SKIP_SUPPRESS_DAYS`）。

- [ ] **Step 3: 实现 `list_suppressed` + 常量**

在 `app/services/restock_decisions.py`：

(a) import 区（现为 `from datetime import UTC, datetime, timedelta`）改为：
```python
from datetime import UTC, date, datetime, timedelta
```
（现为 `from sqlalchemy import desc, select`）改为：
```python
from sqlalchemy import desc, func, select
```
（现为 `from app.models import RestockDecision`）改为：
```python
from app.models import InventoryEvent, RestockDecision
```

(b) 常量区（现有 `STALE_HIGH_SCORE_DAYS = 14` 旁）新增：
```python
SKIP_SUPPRESS_DAYS = 14
```

(c) 在 `list_stale_high_score` 之后插入函数：
```python
def list_suppressed(session: Session) -> dict[str, dict[str, Any]]:
    """skip 抑制集: 每 barcode 最近一条决策是 skipped、在 SKIP_SUPPRESS_DAYS 天内、
    且无后续新进货(MAX purchase event_at 不晚于 skip 日) → 抑制.

    返回 {barcode: {skipped_at, reason, days_left}}. 决策历史不删, 解除只是不返回.
    """
    today = datetime.now(UTC).date()
    cutoff = (today - timedelta(days=SKIP_SUPPRESS_DAYS)).isoformat()  # YYYY-MM-DD
    rows = (
        session.execute(
            select(RestockDecision)
            .where(RestockDecision.decided_at >= cutoff)
            .order_by(desc(RestockDecision.decided_at))
        )
        .scalars()
        .all()
    )
    # 已按 decided_at 倒序: 每 barcode 第一条即最近一条
    latest: dict[str, RestockDecision] = {}
    for r in rows:
        latest.setdefault(r.barcode, r)
    # 候选: 最近一条是 skipped 且 skip 日在窗口内
    candidates: dict[str, RestockDecision] = {}
    for bc, r in latest.items():
        if r.decision != "skipped":
            continue
        skip_date = r.decided_at[:10]
        if (today - date.fromisoformat(skip_date)).days >= SKIP_SUPPRESS_DAYS:
            continue
        candidates[bc] = r
    if not candidates:
        return {}
    # 进货提前解除: 候选 barcode 的 MAX(purchase event_at) 晚于 skip 日 → 剔除
    last_purchase = dict(
        session.execute(
            select(InventoryEvent.product_barcode, func.max(InventoryEvent.event_at))
            .where(
                InventoryEvent.event_type == "purchase",
                InventoryEvent.product_barcode.in_(list(candidates.keys())),
            )
            .group_by(InventoryEvent.product_barcode)
        ).all()
    )
    result: dict[str, dict[str, Any]] = {}
    for bc, r in candidates.items():
        skip_date = r.decided_at[:10]
        lp = last_purchase.get(bc)
        if lp is not None and lp[:10] > skip_date:
            continue
        days_left = SKIP_SUPPRESS_DAYS - (today - date.fromisoformat(skip_date)).days
        result[bc] = {"skipped_at": r.decided_at, "reason": r.reason, "days_left": days_left}
    return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_restock_decisions.py::SuppressedTests -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/restock_decisions.py tests/test_restock_decisions.py
git commit -m "feat(restock): list_suppressed 抑制集查询(14天/进货解除/取最近) + 单测"
```

---

## Task 2: 后端 `GET /restock/decisions/suppressed` 端点

**Files:**
- Modify: `app/routes/restock.py`
- Test: `tests/test_restock_decisions.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_restock_decisions.py` 文件末尾 `if __name__` 之前插入路由 smoke：

```python
class SuppressedRouteTests(_Base):
    def test_suppressed_endpoint(self):
        from server import create_app

        with stockpile_db._session() as s:
            s.add(
                RestockDecision(
                    barcode="R1",
                    decision="skipped",
                    decided_at=SuppressedTests._days_ago(3),
                    reason="等活动",
                    urgency_score=72,
                )
            )
            s.commit()
        app = create_app(seed_users=False, prewarm=False)
        app.config["LOGIN_DISABLED"] = True
        client = app.test_client()
        resp = client.get("/restock/decisions/suppressed")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "R1" in data["items"]
        assert data["items"]["R1"]["reason"] == "等活动"
```

> 注：`create_app` 的鉴权 `before_request` 会拦未登录请求。本测试用 `LOGIN_DISABLED` 跳过 Flask-Login；若该项目 `before_request` 是自定义闸不认 `LOGIN_DISABLED`，改用现有路由测试的登录范式。**实现 Step 前先 grep 确认**：`grep -rn "test_client\|LOGIN_DISABLED\|create_app(" tests/ | head`，照已有路由测试（如 `test_app_factory` / history route 测试）的鉴权写法。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_restock_decisions.py::SuppressedRouteTests -v`
Expected: FAIL — 404（端点不存在）。

- [ ] **Step 3: 加端点**

在 `app/routes/restock.py` 末尾（`get_stale` 之后）插入：

```python
@bp.get("/decisions/suppressed")
def get_suppressed():
    """skip 抑制集: 最近一条是 skipped、14 天内、无后续新进货的 barcode.

    天数走后端常量 SKIP_SUPPRESS_DAYS(业务规则, 不暴露 query).
    """
    with get_session() as s:
        items = svc.list_suppressed(s)
    return jsonify({"ok": True, "items": items})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_restock_decisions.py::SuppressedRouteTests -v`
Expected: 1 passed。若鉴权拦截致 302/401，按 Step 1 注释改用项目登录 helper 后再跑。

- [ ] **Step 5: Commit**

```bash
git add app/routes/restock.py tests/test_restock_decisions.py
git commit -m "feat(restock): GET /restock/decisions/suppressed 端点"
```

---

## Task 3: 前端取数 + 过滤隐藏

**Files:**
- Modify: `static/js/restock.js`

- [ ] **Step 1: `state` 加 `suppressed` + 常量 `SKIP_SUPPRESS_DAYS`**

(a) 常量区（`const HOT_URGENCY = 70;` 旁，约 `restock.js:29`）新增：
```javascript
const SKIP_SUPPRESS_DAYS = 14;   // 与后端 restock_decisions.SKIP_SUPPRESS_DAYS 对齐
```

(b) `state` 对象里（`editedQty: {},` 同级，约 `:49`）新增：
```javascript
  suppressed: {},   // barcode -> {skipped_at, reason, days_left}; 标「不进」后默认隐藏, 后端回流
```

- [ ] **Step 2: `load()` 拉 suppressed**

把 `load()` 里（约 `:1118`）：
```javascript
    state.items = data.items;
    // 货到后自动 unmark
    autoClearOrderedByPurchase();
```
替换为：
```javascript
    state.items = data.items;
    // 货到后自动 unmark
    autoClearOrderedByPurchase();
    // 决策回流: 拉 skip 抑制集(失败兜底空, 不阻断主列表)
    try {
      const sresp = await fetch("/restock/decisions/suppressed");
      const sdata = await sresp.json();
      state.suppressed = sdata.ok ? (sdata.items || {}) : {};
    } catch (_e) {
      state.suppressed = {};
    }
```

- [ ] **Step 3: `_filterPredicate` 加抑制隐藏 / 已跳过 band**

在 `_filterPredicate` 里，`if (isOrdered) return false;`（约 `:298`）之后、`if (state.filter.origin ...)`（约 `:299`）之前插入：
```javascript
  // 决策回流: 非「已跳过」band 隐藏被抑制项; 「已跳过」band 只看被抑制项
  const isSuppressed = it.barcode in state.suppressed;
  if (state.filter.band === "skipped") {
    if (!isSuppressed) return false;
  } else if (isSuppressed) {
    return false;
  }
```

- [ ] **Step 4: 本地验证过滤（人工）**

`dev.ps1` 起本地 PG（或合成 sku_summary）→ 浏览器 console 临时塞 `state.suppressed = {"<某可见行 barcode>": {skipped_at:"2026-06-08 10:00:00", reason:"t", days_left:14}}` 后 `render()` → 该行从默认列表消失；`state.filter.band="skipped"; render()` → 只剩该行。（正式走查在 Task 6。）

- [ ] **Step 5: Commit**

```bash
git add static/js/restock.js
git commit -m "feat(restock): 前端拉 suppressed + 默认隐藏/已跳过 band 过滤"
```

---

## Task 4: 「已跳过」band 按钮 + skipped tag + 样式

**Files:**
- Modify: `templates/partials/_page_restock.html`
- Modify: `static/js/restock.js`
- Modify: `static/css/components.css`

- [ ] **Step 1: band 行加「已跳过」chip**

在 `templates/partials/_page_restock.html` 的 band 行（约 `:31`，`<button class="rs-chip" data-band="flagged">⚑ 已标记</button>`）之后插入：
```html
            <button class="rs-chip" data-band="skipped">⊘ 已跳过</button>
```
（chip 点击切换 / active 同步已由现有通用 handler 处理：`restock.js:1176` 的 `data-band` 委托 + `:878` 的 active 同步，无需改 JS 绑定。）

- [ ] **Step 2: renderRow 加 skipped tag**

在 `renderRow` 里（`orderedTag` 定义之后，约 `:373`）插入：
```javascript
  const sup = state.suppressed[it.barcode];
  const skippedTag = sup
    ? `<span class="rs-tag rs-tag--skip" title="已跳过 ${escapeHtml((sup.skipped_at || '').slice(0,10))}${sup.reason ? ' · ' + escapeHtml(sup.reason) : ''} · 剩 ${sup.days_left ?? '?'} 天">已跳过</span>`
    : "";
```
并把行模板里（约 `:384`）：
```javascript
      <td>${nameCell}${disc}${newTag}${orderedTag}</td>
```
改为：
```javascript
      <td>${nameCell}${disc}${newTag}${orderedTag}${skippedTag}</td>
```

- [ ] **Step 3: 加 `.rs-tag--skip` 样式**

在 `static/css/components.css` 的 `.rs-tag--ordered { ... }`（约 `:2094`）之后插入：
```css
.rs-tag--skip    { background: var(--bg-3); color: var(--ink-2); border: 1px solid var(--line-soft); }
```

- [ ] **Step 4: 本地验证（人工）**

刷新补货页 → band 行出现「⊘ 已跳过」；console 塞 `state.suppressed` 后切该 band → 行带「已跳过」tag，hover 显示 原因+日期+剩余天数；tag 样式与 `已下单` 协调不破行高。（正式走查 Task 6。）

- [ ] **Step 5: Commit**

```bash
git add templates/partials/_page_restock.html static/js/restock.js static/css/components.css
git commit -m "feat(restock): 已跳过 band + skipped tag(原因/日期/剩余天数) + 样式"
```

---

## Task 5: 标「不进」乐观隐藏（POST 成功为准）

**Files:**
- Modify: `static/js/restock.js`

- [ ] **Step 1: `recordDecisionsBatch` 返回成功布尔**

把 `recordDecisionsBatch`（约 `:717`）改为返回 ok（实现前先读 `:717-732` 确认现有结尾，只增加两处 `return`）：
```javascript
async function recordDecisionsBatch(decision, items, reason) {
  try {
    const resp = await fetch("/restock/decisions/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, items, reason: reason || null }),
    });
    const data = await resp.json();
    if (data.ok && data.overridden > 0) {
      console.log(`[restock-decisions] ${data.recorded} 条 (含 ${data.overridden} 个低分覆盖)`);
    }
    return !!data.ok;
  } catch (err) {
    console.warn("[restock-decisions] 失败:", err.message);
    return false;
  }
}
```

- [ ] **Step 2: `markSelectedSkipped` 改为 await 成功后乐观隐藏**

把 `markSelectedSkipped`（约 `:679`）整体替换为：
```javascript
async function markSelectedSkipped() {
  if (state.selected.size === 0) {
    alert("请先勾选要标记的行");
    return;
  }
  const reason = prompt("跳过原因? (可空, 例: 供应商断货 / 客人未确认 / 等下次活动)") ?? "";
  const items = [];
  for (const bc of state.selected) {
    const it = state.items.find((x) => x.barcode === bc);
    if (it) items.push(it);
  }
  if (items.length === 0) return;
  // 硬约束: 先确认 POST 成功, 再乐观隐藏; 失败不隐藏(防前端假状态)
  const ok = await recordDecisionsBatch("skipped", items, reason || null);
  if (!ok) {
    alert("跳过记录失败, 未隐藏, 请重试");
    return;
  }
  const now = new Date().toISOString().slice(0, 19).replace("T", " ");
  for (const it of items) {
    state.suppressed[it.barcode] = {
      skipped_at: now,
      reason: reason || null,
      days_left: SKIP_SUPPRESS_DAYS,
    };
  }
  state.selected.clear();
  render();
}
```

- [ ] **Step 3: `markSingleSkipped` 同样改**

把 `markSingleSkipped`（约 `:708`）整体替换为：
```javascript
async function markSingleSkipped(bc) {
  const it = state.items.find((x) => x.barcode === bc);
  if (!it) return;
  const reason = prompt("跳过原因? (可空, 例: 供应商断货 / 客人未确认 / 等下次活动)") ?? "";
  const ok = await recordDecisionsBatch("skipped", [it], reason || null);
  if (!ok) {
    alert("跳过记录失败, 未隐藏, 请重试");
    return;
  }
  const now = new Date().toISOString().slice(0, 19).replace("T", " ");
  state.suppressed[bc] = { skipped_at: now, reason: reason || null, days_left: SKIP_SUPPRESS_DAYS };
  state.expandedBarcode = null;
  render();
}
```

- [ ] **Step 4: 本地端到端验证（人工）**

`dev.ps1` + 数据 → 勾几行点「✗ 不进」填原因 → POST 成功后这些行**立刻**从默认列表消失；切「已跳过」band 能看到它们带 tag；模拟 POST 失败（DevTools 断网）→ 行不消失 + alert 提示。

- [ ] **Step 5: Commit**

```bash
git add static/js/restock.js
git commit -m "feat(restock): 标「不进」await POST 成功后乐观隐藏(失败不隐藏)"
```

---

## Task 6: 全量验收 + 回归

**Files:** 无新增改动，走查 spec 验收清单 + 全量回归。

- [ ] **Step 1: 后端全量回归**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 全量通过（含新增 SuppressedTests/SuppressedRouteTests）。

- [ ] **Step 2: 本地端到端走查（对照 spec 验收标准）**

`dev.ps1` 起本地 PG，合成几条数据（sku_summary 行 + restock_decisions 行）：
1. 今天标「不进」→ 默认 band 立刻看不到。
2. 「已跳过」band → 看到它 + tag（原因/跳过时间/剩余天数）。
3. 把某条 `decided_at` 改到 15 天前（`docker exec ... psql UPDATE`）→ 刷新 → 重新出现在正常候选。
4. 给某被抑制 barcode 插一条 `event_at` 晚于 skip 日的 purchase event → 刷新 → 提前解除、重新出现。
5. 给某 barcode 在 skip 后再记一条 ordered → 刷新 → 不再被抑制。
6. suppressed 端点 500/断网 → 主列表照常显示（降级不抑制）。

- [ ] **Step 3: 确认改动面**

Run: `git diff --stat main...feat/restock-skip-suppression`
Expected: 仅 `app/services/restock_decisions.py`、`app/routes/restock.py`、`tests/test_restock_decisions.py`、`static/js/restock.js`、`templates/partials/_page_restock.html`、`static/css/components.css`（+ docs/specs、docs/plans）。**无 `restock_calc.py`、无 `models.py`、无 alembic 文件**（验证"不改评分算法/DB schema"）。

- [ ] **Step 4: 收尾**

实现完成后走 `superpowers:finishing-a-development-branch` 决定合并方式（按用户 git 规范：feat 分支 → squash merge 回 main；push main 被护栏 hook 拦，需用户自己 `!git push`）。

---

## Self-Review（plan 作者自检）

- **Spec coverage:**
  - 后端 `list_suppressed` 规则（最近是 skipped/14天内/进货解除/取最近）→ Task 1 + 6 测试用例全覆盖。
  - 端点 `GET /restock/decisions/suppressed`（无 query、常量 14）→ Task 2。
  - 前端取数 `state.suppressed` + 失败兜底 → Task 3 Step 2。
  - 默认隐藏 + 「已跳过」band 翻出 → Task 3 Step 3 + Task 4。
  - skipped tag（原因/时间/剩余天数）→ Task 4 Step 2。
  - 乐观隐藏 = POST 成功为准（硬约束）→ Task 5。
  - 不改评分算法/DB schema → Task 6 Step 3 改动面断言。
  - 决策历史不删 → `list_suppressed` 纯查询无 delete；Task 1 实现保证。
- **Placeholder scan:** 无 TBD/TODO；每个代码步骤含完整代码。Task 2 Step 1 的登录 helper 留了"先 grep 确认项目范式"的明确动作（非占位，是适配现有鉴权的必要探查）。
- **Type consistency:** `list_suppressed(session)→dict[str,dict]`、`SKIP_SUPPRESS_DAYS`（后端 service + 前端常量同名同值 14）、`state.suppressed`、端点返回 `{ok, items}`、payload 键 `{skipped_at, reason, days_left}`、band 值 `"skipped"`、tag class `.rs-tag--skip`、`recordDecisionsBatch` 返回 bool —— 跨任务命名/结构一致。
