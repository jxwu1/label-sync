# 预测效果看板 UI 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增只读「预测效果」导航页，消费 `GET /analytics/backtest/dashboard`，展示数据新鲜度 + headline KPI + 置信度分布 + 按 SKU 类型表 + 模型对比表。

**Architecture:** 纯前端。新导航项（`store.js`）+ 页面容器 + 脚本挂载（`index.html`）+ 独立模块 `static/js/forecast_eval.js`（`onFirstActivate` 懒加载，fetch 端点，innerHTML 渲染）+ CSS（`components.css`）。后端零改动。

**Tech Stack:** Vanilla JS（ES module）+ Alpine store nav + 手写 CSS。后端端点 `/analytics/backtest/dashboard` 已上线并测过。

> **测试说明：** 无 JS 单测框架（YAGNI 不引入）。验证 = 本地浏览器手测 + Playwright 截图。本地 PG 可能无 backtest 数据 → 默认空/缺态；正常态用 Task 4 的 seed 片段或部署后对线上 run 44 核对。

---

## 文件结构

- **Modify** `static/js/store.js` — `pages` 数组加一项导航。
- **Modify** `templates/index.html` — 加页面容器 `<div id="pageForecastEval">` + 底部脚本挂载。
- **Create** `static/js/forecast_eval.js` — 看板模块（fetch + 渲染 + 空态 + 刷新）。
- **Modify** `static/css/components.css` — KPI 条 / tier 三色条 / 表格样式。

---

## Task 1: 导航接线（nav 项 + 页面容器 + 脚本挂载）

**Files:**
- Modify: `static/js/store.js`
- Modify: `templates/index.html`

- [ ] **Step 1: store.js 加导航项**

在 `static/js/store.js` 的 `pages` 数组里，`foreign_customers`（code 08）那项之后、`restock`（code 11）那项之前，插入：
```javascript
      { id: "forecast_eval",     label: "预测效果",   icon: "sales",      code: "09", shortcut: "9" },
```

- [ ] **Step 2: index.html 加页面容器**

在 `templates/index.html` 里，紧邻其它 `<div class="page" id="page...">` 容器（例如 `pageForeignCustomers` 或 `pageSalesAnalytics` 附近），新增一行空容器：
```html
      <div class="page" id="pageForecastEval" x-data :class="$store.nav.current === 'forecast_eval' ? 'active' : ''"></div>
```

- [ ] **Step 3: index.html 加脚本挂载**

在 `templates/index.html` 底部 `<script type="module">` 块（现约 1493–1506，挨着 `sales-analytics.js` 那行）加：
```html
<script type="module" src="{{ url_for('static', filename='js/forecast_eval.js') }}"></script>
```

- [ ] **Step 4: 提交**

```bash
git add static/js/store.js templates/index.html
git commit -m "feat(forecast-ui): 预测效果导航项 + 页面容器 + 脚本挂载"
```

> 此时点导航「预测效果」会切到空页（模块下一个 Task 才建）。确认导航项出现、点击切页无报错即可。

---

## Task 2: forecast_eval.js 看板模块

**Files:**
- Create: `static/js/forecast_eval.js`

- [ ] **Step 1: 创建模块，完整内容**

创建 `static/js/forecast_eval.js`：

```javascript
import { esc } from "./shared.js";

const PAGE = "forecast_eval";

// 指标格式化（单位见 spec）：
// median_mase 浮点→2位; beats_naive_pct 已×100→整数%; coverage 0-1→×100整数%; null→—
const fmtMase = (v) => (v == null ? "—" : Number(v).toFixed(2));
const fmtPct = (v) => (v == null ? "—" : Math.round(Number(v)) + "%");
const fmtCov = (v) => (v == null ? "—" : Math.round(Number(v) * 100) + "%");

function render(container, d) {
  const missing = d.run_id == null;
  const h = d.headline || {};
  const t = d.tiers || { high: 0, medium: 0, low: 0 };
  const total = (t.high || 0) + (t.medium || 0) + (t.low || 0) || 1;
  const pct = (n) => (((n || 0) / total) * 100).toFixed(1);
  const byType = d.by_sku_type || [];
  const models = d.models || []; // 不保证 6 行，空则表内 —

  container.innerHTML = `
    <div class="fe-wrap">
      <div class="fe-head">
        <h2 class="fe-title">预测效果</h2>
        <span class="fe-fresh">${
          missing ? "尚无回测数据" : `run #${esc(String(d.run_id))} · ${esc(d.backtest_date || "—")}`
        }</span>
        <span class="fe-spacer"></span>
        <button class="btn btn--ghost" id="feRefresh" type="button">↻ 刷新</button>
      </div>

      ${missing ? `<div class="fe-banner">尚无回测数据，置信度全部按缺失评为低。先触发一次 backtest 再来看。</div>` : ""}

      <div class="fe-kpis">
        <div class="fe-kpi"><span class="fe-kpi-v">${fmtPct(h.beats_naive_pct)}</span><span class="fe-kpi-l">MASE&lt;1 占比</span></div>
        <div class="fe-kpi"><span class="fe-kpi-v">${fmtMase(h.median_mase)}</span><span class="fe-kpi-l">中位 MASE</span></div>
        <div class="fe-kpi"><span class="fe-kpi-v">${fmtCov(h.avg_coverage_p98)}</span><span class="fe-kpi-l">覆盖 @p98</span></div>
        <div class="fe-kpi"><span class="fe-kpi-v">${esc(String(d.scored_skus ?? 0))}/${esc(String(d.forecast_skus ?? 0))}</span><span class="fe-kpi-l">评分 / 预测 SKU</span></div>
      </div>

      <div class="fe-tiers">
        <span class="fe-tiers-label">置信度分布</span>
        <div class="fe-bar">
          <div class="fe-seg fe-seg--high" style="width:${pct(t.high)}%"></div>
          <div class="fe-seg fe-seg--medium" style="width:${pct(t.medium)}%"></div>
          <div class="fe-seg fe-seg--low" style="width:${pct(t.low)}%"></div>
        </div>
        <div class="fe-legend">
          <span><i class="fe-dot fe-dot--high"></i>高 ${t.high || 0}</span>
          <span><i class="fe-dot fe-dot--medium"></i>中 ${t.medium || 0}</span>
          <span><i class="fe-dot fe-dot--low"></i>低 ${t.low || 0}</span>
        </div>
      </div>

      <section class="pnl fe-pnl">
        <div class="pnl-hd"><span class="pnl-title">按 SKU 类型</span></div>
        <div class="pnl-bd">
          <table class="fe-table">
            <thead><tr><th>SKU 类型</th><th class="fe-num">评分数</th><th class="fe-num">中位MASE</th><th class="fe-num">胜Naive%</th><th class="fe-num">覆盖</th></tr></thead>
            <tbody>${
              byType.length
                ? byType
                    .map(
                      (r) =>
                        `<tr><td>${esc(r.sku_type || "—")}</td><td class="fe-num">${esc(String(r.n ?? 0))}</td><td class="fe-num">${fmtMase(r.median_mase)}</td><td class="fe-num">${fmtPct(r.beats_naive_pct)}</td><td class="fe-num">${fmtCov(r.avg_coverage_p98)}</td></tr>`
                    )
                    .join("")
                : `<tr><td colspan="5" class="fe-empty">—</td></tr>`
            }</tbody>
          </table>
        </div>
      </section>

      <section class="pnl fe-pnl">
        <div class="pnl-hd"><span class="pnl-title">模型对比</span></div>
        <div class="pnl-bd">
          <table class="fe-table">
            <thead><tr><th>模型</th><th class="fe-num">中位MASE</th><th class="fe-num">胜Naive%</th><th class="fe-num">覆盖</th><th>生产</th></tr></thead>
            <tbody>${
              models.length
                ? models
                    .map(
                      (m) =>
                        `<tr class="${m.is_production ? "fe-row--prod" : ""}"><td>${esc(m.model_name || "—")}</td><td class="fe-num">${fmtMase(m.median_mase)}</td><td class="fe-num">${fmtPct(m.beats_naive_pct)}</td><td class="fe-num">${fmtCov(m.avg_coverage_p98)}</td><td>${m.is_production ? "★" : ""}</td></tr>`
                    )
                    .join("")
                : `<tr><td colspan="5" class="fe-empty">—</td></tr>`
            }</tbody>
          </table>
        </div>
      </section>
    </div>`;

  const btn = container.querySelector("#feRefresh");
  if (btn) btn.addEventListener("click", load);
}

async function load() {
  const container = document.getElementById("pageForecastEval");
  if (!container) return;
  container.innerHTML = `<div class="fe-loading">加载中…</div>`;
  try {
    const res = await fetch("/analytics/backtest/dashboard");
    const data = await res.json();
    if (!data.ok) {
      container.innerHTML = `<div class="fe-banner">加载失败：${esc(data.msg || "")}</div>`;
      return;
    }
    render(container, data);
  } catch (e) {
    container.innerHTML = `<div class="fe-banner">加载失败（网络）</div>`;
  }
}

// 稳妥注册（对齐 admin.js）：模块加载时 Alpine 可能还没就绪，
// 用 optional-chaining (?.) 会静默跳过 → onFirstActivate 永不注册、页面永不加载。
// 改成：Alpine 已在则直接注册，否则等 alpine:init 事件。
function register() {
  Alpine.store("nav").onFirstActivate(PAGE, load);
}

if (window.Alpine) {
  register();
} else {
  document.addEventListener("alpine:init", register);
}
```

- [ ] **Step 2: 静态检查**

Run: `node --check static/js/forecast_eval.js`（ES module import 若报 CommonJS 警告忽略，确保无真语法错；或 `npx --yes acorn --module --ecma2022 static/js/forecast_eval.js > /dev/null`）。
确认 `esc` 从 shared.js 导出：`grep -n "export function esc" static/js/shared.js`。

- [ ] **Step 3: 浏览器验证（至少空态）**

`./dev.ps1` 起服务，点导航「预测效果」。本地若无 backtest 数据 → 应显示：标题 + 「尚无回测数据」黄条 + tier 全低条 + 两表 `—` + headline `—`。控制台无报错。点「↻ 刷新」重新拉取。

- [ ] **Step 4: 提交**

```bash
git add static/js/forecast_eval.js
git commit -m "feat(forecast-ui): 看板模块(KPI+置信度分布+两表+空态+刷新)"
```

---

## Task 3: CSS — KPI 条 / tier 三色条 / 表格

**Files:**
- Modify: `static/css/components.css`（末尾追加）

- [ ] **Step 1: 追加样式块**

在 `static/css/components.css` 末尾追加：

```css
/* ── 预测效果看板 ───────────────────────────────── */
.fe-wrap { display: flex; flex-direction: column; gap: var(--sp-4); padding: 20px 24px; }
.fe-head { display: flex; align-items: baseline; gap: var(--sp-3); }
.fe-title { font-size: var(--fs-lg); font-weight: 700; color: var(--ink-1); margin: 0; }
.fe-fresh { font-size: var(--fs-sm); color: var(--ink-3); }
.fe-spacer { flex: 1; }
.fe-banner { background: color-mix(in srgb, var(--warning, #E5A50A) 16%, transparent); color: var(--warning, #E5A50A); border: 1px solid color-mix(in srgb, var(--warning, #E5A50A) 40%, transparent); border-radius: var(--r-sm); padding: var(--sp-2) var(--sp-3); font-size: var(--fs-sm); }
.fe-loading { padding: 40px; text-align: center; color: var(--ink-3); }

.fe-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--sp-3); }
.fe-kpi { display: flex; flex-direction: column; gap: 2px; background: var(--bg-1); border: 1px solid var(--line-soft); border-radius: var(--r-md); padding: var(--sp-3) var(--sp-4); }
.fe-kpi-v { font-size: var(--fs-xl); font-weight: 700; color: var(--ink-1); font-variant-numeric: tabular-nums; }
.fe-kpi-l { font-size: var(--fs-xs); color: var(--ink-3); text-transform: uppercase; }

.fe-tiers { display: flex; flex-direction: column; gap: var(--sp-2); }
.fe-tiers-label { font-size: var(--fs-xs); color: var(--ink-3); text-transform: uppercase; }
.fe-bar { display: flex; height: 16px; border-radius: var(--r-sm); overflow: hidden; background: var(--bg-2); }
.fe-seg { height: 100%; }
.fe-seg--high { background: #2E9E5B; }
.fe-seg--medium { background: #E5A50A; }
.fe-seg--low { background: #80808A; }
.fe-legend { display: flex; gap: var(--sp-4); font-size: var(--fs-sm); color: var(--ink-2); }
.fe-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.fe-dot--high { background: #2E9E5B; }
.fe-dot--medium { background: #E5A50A; }
.fe-dot--low { background: #80808A; }

.fe-pnl .pnl-bd { padding: 0; }
.fe-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.fe-table th, .fe-table td { padding: var(--sp-2) var(--sp-3); text-align: left; border-bottom: 1px solid var(--line-soft); white-space: nowrap; }
.fe-table th { color: var(--ink-3); font-weight: 600; font-size: var(--fs-xs); text-transform: uppercase; }
.fe-table td.fe-num, .fe-table th.fe-num { text-align: right; font-variant-numeric: tabular-nums; }
.fe-row--prod { background: color-mix(in srgb, var(--accent) 10%, transparent); font-weight: 600; }
.fe-empty { text-align: center; color: var(--ink-3); }
```

> 注：用到 `--warning` 时给了 fallback `#E5A50A`；若 `tokens.css` 已有 `--warning` 则用 token。实现时 Grep 抽查 `--ink-1`/`--fs-lg`/`--fs-xl`/`--r-md`/`--accent` 在 `static/css/tokens.css` 存在，缺则换最接近的现有 token 并在提交信息注明。

- [ ] **Step 2: 浏览器验证样式**

刷新预测效果页，确认 KPI 卡片 4 列、tier 三色条配色、表格对齐、生产模型行高亮在暗色下正常。

- [ ] **Step 3: 提交**

```bash
git add static/css/components.css
git commit -m "feat(forecast-ui): 看板 CSS(KPI条/置信度三色条/表格)"
```

---

## Task 4: 验证（空态 + seed 正常态 + 暗亮截图）

**Files:** 无（纯验证）

- [ ] **Step 1: 空/缺态**

本地无 backtest 数据时开页 → 黄条 + 全低 tier + 两表 `—` + headline `—`，布局不裂。

- [ ] **Step 2: seed 正常态**

Run（`./dev.ps1` 服务在跑时另开终端）：
```powershell
.venv\Scripts\python.exe -c "from server import create_app; from app.models import BacktestRun, BacktestResult, ForecastOutput, get_session; from sqlalchemy import insert; app=create_app();
with get_session() as s:
    run = s.execute(insert(BacktestRun).values(model_name='EmpiricalQuantile', view='base_demand', window_train=52, window_test=8, min_weeks=20, n_skus_total=3, n_skus_scored=3)).inserted_primary_key[0]
    s.execute(insert(BacktestRun).values(model_name='CrostonSBA', view='base_demand', window_train=52, window_test=8, min_weeks=20, n_skus_total=3, n_skus_scored=3))
    for bc, st, mase, cov in [('B1','retail_dominant',0.81,0.97),('B2','mixed',0.95,0.94),('B3','wholesale_only',1.20,0.93)]:
        s.execute(insert(BacktestResult).values(run_id=run, product_barcode=bc, sku_type=st, n_weeks_train=52, n_weeks_test=8, mase=mase, bias=0.0, coverage_p98=cov, mean_actual=10.0, mean_predicted=10.0))
        s.execute(insert(ForecastOutput).values(product_barcode=bc, model_used='EmpiricalQuantile', sku_type=st, n_weeks_history=60, nonzero_weeks=14, zero_weeks_last8=1, mu=10.0, sigma=3.0, p50=9.0, p98=18.0))
    s.commit()
print('seeded')"
```
刷新页面，确认：
- 头部 `run #<id> · <日期>`，黄条消失。
- KPI：MASE<1占比 ≈ 67%（3 单里 2 单 <1）、中位MASE 0.95、覆盖 ≈ 95%、评分 3/3。
- tier 三色条按高/中/低比例渲染。
- 「按 SKU 类型」表 3 行（retail_dominant/mixed/wholesale_only）。
- 「模型对比」表至少 2 行（EmpiricalQuantile ★ 高亮、CrostonSBA）。

- [ ] **Step 3: 暗/亮主题截图**

切主题，KPI 卡 / 三色条 / 表格 / 生产行高亮在两主题对比度正常。

- [ ] **Step 4: 清理 seed（可选）**

```powershell
.venv\Scripts\python.exe -c "from server import create_app; from app.models import BacktestRun, BacktestResult, ForecastOutput, get_session; from sqlalchemy import delete; app=create_app();
with get_session() as s:
    s.execute(delete(ForecastOutput).where(ForecastOutput.product_barcode.in_(['B1','B2','B3'])));
    s.execute(delete(BacktestResult).where(BacktestResult.product_barcode.in_(['B1','B2','B3'])));
    s.execute(delete(BacktestRun).where(BacktestRun.view=='base_demand', BacktestRun.n_skus_total==3));
    s.commit(); print('cleaned')"
```

- [ ] **Step 5: 完成开发分支**

调用 superpowers:finishing-a-development-branch（按约定 squash merge 回 main；push 由用户手动触发部署）。

---

## Self-Review（计划自检）

- **Spec 覆盖**：导航项+容器+脚本挂载（Task 1，含 spec 强调的脚本挂载）/ 五渲染块（Task 2）/ `models||[]` 不硬编码 6 行（Task 2 render）/ 格式化单位（Task 2 fmt*）/ 空态 run_id===null（Task 2 missing）/ 转义 sku_type+model_name（Task 2 esc）/ 工作台风格无 hero（Task 2 结构 + Task 3 CSS）/ 三色条+两表+KPI CSS（Task 3）/ 空态+seed+截图验证（Task 4）—— 全覆盖。
- **占位符**：无 TBD；每个改码步骤都有完整代码。
- **类型/命名一致**：`PAGE="forecast_eval"` 与 store.js 导航 id、index.html `pageForecastEval`、`onFirstActivate` 注册一致；`fmtMase/fmtPct/fmtCov` 定义与各调用点一致；CSS 类名（fe-wrap/fe-kpi/fe-seg/fe-table/fe-row--prod）模块与 CSS 两边对应；端点字段（run_id/backtest_date/tiers/headline/by_sku_type/models + 各 metric 名）与后端 `build_forecast_eval_dashboard` 返回一致。
