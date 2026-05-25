"use strict";

const THEMES = [
  { id: "apple-dark",  label: "Apple Dark",  desc: "纯黑底 + 蓝强调",     bg: "#000", accent: "#007AFF", fg: "#fff" },
  { id: "apple-light", label: "Apple Light", desc: "纯白底 + 蓝强调",     bg: "#F2F2F7", accent: "#007AFF", fg: "#000" },
  { id: "terminal",    label: "Terminal",     desc: "暗色终端 + 绿强调",   bg: "#0a0d12", accent: "#00ff95", fg: "#e6ebf2" },
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
  const current = document.body.dataset.theme || "apple-dark";
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

if (window.Alpine) {
  Alpine.store("nav").onFirstActivate("admin", () => {
    renderThemePicker();
    renderSettings();
    renderUsers();
    initAddUser();
  });
} else {
  document.addEventListener("alpine:init", () => {
    Alpine.store("nav").onFirstActivate("admin", () => {
      renderThemePicker();
      renderSettings();
      renderUsers();
      initAddUser();
    });
  });
}
