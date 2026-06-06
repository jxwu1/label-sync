"use strict";

const THEMES = [
  { id: "dark",  label: "Dark",  desc: "近纯黑底 + 红强调",  bg: "#0A0A0B", accent: "#E5484D", fg: "#EDEDEF" },
  { id: "light", label: "Light", desc: "纯白底 + 红强调",    bg: "#FFFFFF", accent: "#DC3545", fg: "#1A1A1E" },
];

const SETTING_LABELS = {
  cn_exchange_rate_rmb_per_eur: "人民币汇率 (RMB/EUR)",
  cn_shipping_rate_rmb_per_m3: "中国运费 (RMB/m³)",
  retail_to_wholesale_ratio: "零售倍率 (零售价/批发价)",
};

function $(id) { return document.getElementById(id); }

async function api(url, opts = {}) {
  const r = await fetch(url, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  return r.json();
}

function renderThemePicker() {
  const box = $("adminThemePicker");
  if (!box) return;
  const current = document.body.dataset.theme || "dark";
  box.innerHTML = THEMES.map(t => `
    <button class="adm-theme-card${t.id === current ? ' adm-theme-card--active' : ''}"
            data-theme="${t.id}"
            style="border:2px solid ${t.id === current ? 'var(--accent)' : 'var(--line)'};
                   background:${t.bg};color:${t.fg};padding:14px 18px;border-radius:var(--r-md);
                   cursor:pointer;min-width:140px;text-align:left;font-family:var(--sans);">
      <div style="font-weight:600;font-size:var(--fs-base);margin-bottom:4px;">${t.label}</div>
      <div style="font-size:var(--fs-sm);opacity:.7;">${t.desc}</div>
      <div style="width:100%;height:4px;border-radius:2px;background:${t.accent};margin-top:8px;"></div>
    </button>
  `).join("");

  box.querySelectorAll("[data-theme]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const theme = btn.dataset.theme;
      const j = await api("/admin/api/theme", { method: "PUT", body: JSON.stringify({ theme }) });
      if (j.ok) {
        document.body.dataset.theme = theme;
        document.documentElement.dataset.theme = theme;
        try { localStorage.setItem("theme", theme); } catch (_) {}
        if (window.Alpine) Alpine.store("theme").current = theme;
        renderThemePicker();
      }
    });
  });
}

async function renderSettings() {
  const box = $("adminSettings");
  if (!box) return;
  const data = await api("/admin/api/settings");
  box.innerHTML = Object.entries(SETTING_LABELS).map(([key, label]) => `
    <label style="color:var(--ink-1);">${label}</label>
    <input data-key="${key}" value="${data[key] || ''}"
           style="padding:6px 10px;background:var(--bg-2);border:1px solid var(--line);
                  border-radius:var(--r-sm);color:var(--ink-0);font-family:var(--mono);
                  font-size:var(--fs-base);outline:none;">
  `).join("");

  $("adminSaveSettings").onclick = async () => {
    const payload = {};
    box.querySelectorAll("input[data-key]").forEach(inp => {
      payload[inp.dataset.key] = inp.value.trim();
    });
    const j = await api("/admin/api/settings", { method: "PUT", body: JSON.stringify(payload) });
    if (j.ok) {
      $("adminSaveSettings").textContent = "已保存 ✓";
      setTimeout(() => { $("adminSaveSettings").textContent = "保存参数"; }, 1500);
    }
  };
}

async function renderUsers() {
  const tbody = $("adminUserTbody");
  if (!tbody) return;
  const users = await api("/admin/api/users");
  tbody.innerHTML = users.map(u => `
    <tr style="border-bottom:1px solid var(--line-soft);">
      <td style="padding:8px 14px;font-family:var(--mono);color:var(--ink-2);">${u.id}</td>
      <td style="padding:8px 14px;">${esc(u.username)}</td>
      <td style="padding:8px 14px;color:var(--ink-1);">${esc(u.display_name || "—")}</td>
      <td style="padding:8px 14px;font-size:var(--fs-sm);">${esc(u.theme)}</td>
      <td style="padding:8px 14px;font-size:var(--fs-sm);color:var(--ink-2);">${u.created_at || "—"}</td>
      <td style="padding:8px 14px;text-align:right;">
        <button class="adm-btn" data-edit="${u.id}">改密码</button>
        <button class="adm-btn adm-btn--danger" data-del="${u.id}">删除</button>
      </td>
    </tr>
  `).join("");

  tbody.querySelectorAll("[data-edit]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const pw = prompt("输入新密码:");
      if (!pw) return;
      await api(`/admin/api/users/${btn.dataset.edit}`, {
        method: "PUT", body: JSON.stringify({ password: pw }),
      });
      alert("密码已更新");
    });
  });

  tbody.querySelectorAll("[data-del]").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm("确认删除此用户?")) return;
      const j = await api(`/admin/api/users/${btn.dataset.del}`, { method: "DELETE" });
      if (j.ok) renderUsers();
      else alert(j.error || "删除失败");
    });
  });
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function initAddUser() {
  const btn = $("adminAddUser");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const username = prompt("用户名:");
    if (!username) return;
    const password = prompt("密码:");
    if (!password) return;
    const display_name = prompt("显示名 (可留空):") || "";
    const j = await api("/admin/api/users", {
      method: "POST",
      body: JSON.stringify({ username, password, display_name }),
    });
    if (j.ok) renderUsers();
    else alert(j.error || "创建失败");
  });
}

// ===== 09 合并：系统状态 / Scraper 新鲜度 / 近期 import / 应急上传（并入数据健康 07）=====
const INV_TYPE_CN = { purchase: "采购", sale: "销售", sales: "销售", snapshot: "库存快照", product: "产品总档" };

function _fmtAgo(iso) {
  if (!iso) return '<span style="color:var(--ink-3)">—</span>';
  const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  const color = days > 14 ? "var(--error)" : days > 7 ? "var(--warn)" : "var(--success)";
  const tag = days > 14 ? "⚠" : days > 7 ? "·" : "✓";
  return `<span style="color:${color}">${iso.slice(0, 10)} ${tag} ${days}天前</span>`;
}

async function renderSysStatus() {
  const box = $("sysStatus");
  if (!box) return;
  try {
    const s = await fetch("/inventory/stats").then((r) => r.json());
    if (!s.ok) throw new Error(s.msg || "stats 失败");
    const lastImp = [s.last_sale_import, s.last_purchase_import, s.last_inventory_snapshot_import]
      .filter(Boolean).sort().pop();
    const row = (label, val, dot = "ok") =>
      `<div class="sys-row"><span class="sys-dot ${dot}"></span><span class="sys-label">${label}</span><span class="sys-val">${val}</span></div>`;
    box.innerHTML =
      row("服务器", "运行中") +
      row("Stockpile DB", `${(s.skus_total || 0).toLocaleString()} active SKU`) +
      row("上次导入", lastImp ? lastImp.slice(0, 16).replace("T", " ") : "—", lastImp ? "ok" : "warn") +
      row("销售事件", (s.events_sale || 0).toLocaleString()) +
      row("采购事件", (s.events_purchase || 0).toLocaleString()) +
      row("客户 / 供应商", `${(s.customers_total || 0).toLocaleString()} / ${(s.suppliers_total || 0).toLocaleString()}`);
  } catch (e) {
    box.innerHTML = `<div class="sys-row"><span class="sys-dot err"></span><span class="sys-label">加载失败</span><span class="sys-val">${esc(e.message)}</span></div>`;
  }
}

async function renderScraper() {
  const box = $("sysScraper");
  if (!box) return;
  try {
    const s = await fetch("/inventory/stats").then((r) => r.json());
    const sched = (name, iso) =>
      `<div class="sched-row"><span class="sched-name">${name}</span><span class="sched-cron">0 4 * * *</span><span class="sched-last">最新 ${_fmtAgo(iso)}</span><button class="sched-btn" disabled title="抓取是外部脚本，暂不支持页面触发">▶ 手动</button></div>`;
    box.innerHTML =
      sched("销售数据", s.latest_sale_at) +
      sched("采购数据", s.latest_purchase_at) +
      sched("库存快照", s.latest_inventory_snapshot_at) +
      sched("产品总档", s.latest_product_master_at);
    const pill = $("sysScrPill");
    if (pill) {
      const dates = [s.latest_sale_at, s.latest_purchase_at, s.latest_inventory_snapshot_at, s.latest_product_master_at].filter(Boolean);
      const maxDays = dates.length
        ? Math.max(...dates.map((d) => Math.floor((Date.now() - new Date(d.length === 10 ? d + "T00:00:00" : d).getTime()) / 86400000)))
        : 999;
      if (maxDays > 14) { pill.textContent = "数据陈旧"; pill.className = "pill pill--warn"; }
      else { pill.textContent = "正常"; pill.className = "pill pill--success"; }
    }
  } catch (e) {
    box.innerHTML = `<div class="sched-row"><span class="sched-name" style="color:var(--error)">加载失败</span></div>`;
  }
}

async function renderRecentImports() {
  const tbody = $("sysImportsBody");
  if (!tbody) return;
  try {
    const r = await fetch("/inventory/imports?limit=10").then((x) => x.json());
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
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" class="pnl-empty">加载失败：${esc(e.message)}</td></tr>`;
  }
}

function _sysInvType() {
  const r = document.querySelector('input[name="sysInvType"]:checked');
  return r ? r.value : "purchase";
}

function initSysUpload() {
  const file = $("sysInvFile");
  const msg = $("sysInvMsg");
  if (!file) return;
  const setMsg = (html, err) => { if (msg) { msg.innerHTML = html; msg.style.color = err ? "var(--error)" : "var(--ink-2)"; } };
  file.addEventListener("change", () => {
    $("sysInvFileName").textContent = file.files[0] ? file.files[0].name : "未选择任何文件";
  });
  $("sysInvPreview")?.addEventListener("click", async () => {
    const f = file.files[0];
    if (!f) return setMsg("请先选择文件", true);
    setMsg("解析中…");
    const fd = new FormData(); fd.append("file", f);
    try {
      const d = await fetch("/inventory/preview", { method: "POST", body: fd }).then((r) => r.json());
      if (!d.ok) return setMsg(`预览失败：${esc(d.msg || "未知错误")}`, true);
      setMsg(`预览成功：${d.row_count} 行 / ${(d.columns || []).length} 列。可直接「执行导入」（用已保存/默认列映射）。`);
    } catch (e) { setMsg(`网络错误：${esc(e.message)}`, true); }
  });
  $("sysInvImport")?.addEventListener("click", async () => {
    const f = file.files[0];
    if (!f) return setMsg("请先选择文件", true);
    const type = _sysInvType();
    setMsg(`正在导入到 ${INV_TYPE_CN[type] || type} …`);
    const fd = new FormData(); fd.append("file", f);
    try {
      const d = await fetch(`/inventory/import/${type}`, { method: "POST", body: fd }).then((r) => r.json());
      if (!d.ok) return setMsg(`导入失败：${esc(d.msg || "未知错误")}`, true);
      setMsg(`导入完成：入库 <b>${d.rows_imported}</b> · 跳过重复 ${d.rows_skipped_duplicate ?? 0} · 新建客户 ${d.new_customers ?? 0} / 供应商 ${d.new_suppliers ?? 0} / SKU ${d.new_skus ?? 0}`);
      renderRecentImports(); renderSysStatus(); renderScraper();
    } catch (e) { setMsg(`网络错误：${esc(e.message)}`, true); }
  });
}

function initSysRefresh() {
  $("sysRefresh")?.addEventListener("click", () => { renderSysStatus(); renderScraper(); });
  $("sysImportsRefresh")?.addEventListener("click", renderRecentImports);
}

function initCollapsible() {
  document.querySelectorAll("#pageAdmin .pnl--clps > .pnl-hd").forEach((hd) => {
    const toggle = (e) => {
      // header bar 里的交互控件（刷新按钮等）不触发折叠
      if (e.target.closest("button, a, input, label, select")) return;
      hd.closest(".pnl")?.classList.toggle("is-collapsed");
    };
    hd.addEventListener("click", toggle);
    hd.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggle(e);
      }
    });
  });
}

function initAdminPage() {
  renderThemePicker();   // #adminThemePicker 已移除时安全跳过（主题切换在侧栏底部）
  renderSettings();
  renderUsers();
  initAddUser();
  renderSysStatus();
  renderScraper();
  renderRecentImports();
  initSysUpload();
  initSysRefresh();
  initCollapsible();
}

if (window.Alpine) {
  Alpine.store("nav").onFirstActivate("admin", initAdminPage);
} else {
  document.addEventListener("alpine:init", () => {
    Alpine.store("nav").onFirstActivate("admin", initAdminPage);
  });
}
