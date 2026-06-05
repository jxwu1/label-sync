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
function register() {
  Alpine.store("nav").onFirstActivate(PAGE, load);
}

if (window.Alpine) {
  register();
} else {
  document.addEventListener("alpine:init", register);
}
