// Alpine stores — 阶段 2 SSOT + PR-FE-1 加 theme / clock / nav.collapsed
// 所有跨页 UI 状态都集中在这里。遗留模块直接调 Alpine.store('xxx').yyy(...)
"use strict";

document.addEventListener("alpine:init", () => {
  // ===== 终端日志 =====
  Alpine.store("term", {
    logs: [],
    lastLog: 0,
    push(text, cls = "", src = "lp") {
      this.logs.push({ text, cls, src });
    },
    clear() {
      this.logs = [];
      this.lastLog = 0;
    },
    setLastLog(n) {
      this.lastLog = n;
    },
  });

  // ===== 全局 badge / status =====
  Alpine.store("app", {
    badgeType: "idle",
    badgeText: "在线",
    statusText: "请先上传文件",
    statusCls: "",
    setBadge(type, text) {
      this.badgeType = type;
      this.badgeText = text;
    },
    setStatus(text, cls = "") {
      this.statusText = text;
      this.statusCls = cls;
    },
  });

  // ===== 文件队列（按批次追踪） =====
  Alpine.store("upload", {
    selected: [],
    batches: [],
    add(files) {
      this.selected.push(...files);
    },
    remove(i) {
      this.selected.splice(i, 1);
    },
    markDone(batchId) {
      if (!batchId) return;
      const names = this.selected.map(f => f.name);
      this.batches.unshift({ id: batchId, files: names, status: "done", ts: Date.now() });
      this.selected = [];
    },
    clear() {
      this.selected = [];
      this.batches = [];
    },
  });

  // ===== 浮层 / 红点 =====
  // 终端日志 store('term') 仍保留（其他模块还在 push logs）；浮窗已删。
  // 互传也搬到 nav module 10，drawer/transferDot/quickTransferDot 一并去掉。
  Alpine.store("ui", {
    quickMenu: false,
    toggleQuick() {
      this.quickMenu = !this.quickMenu;
    },
    closeQuick() {
      this.quickMenu = false;
    },
  });

  // ===== 跨端消息 =====
  Alpine.store("messages", {
    list: [],
    setList(items) {
      this.list = items;
    },
  });

  // ===== 互传文件列表 =====
  Alpine.store("transfer", {
    files: [],
    setFiles(items) {
      this.files = items;
    },
  });

  // ===== 主题 =====
  // 双主题: dark / light (Linear 风格)
  // FOUC 防御：index.html <head> inline script 已设置 body.dataset.theme
  const THEMES = ["dark", "light"];
  Alpine.store("theme", {
    current: document.body.dataset.theme || "dark",
    isDark() {
      return this.current === "dark";
    },
    toggle() {
      this.set(this.current === "dark" ? "light" : "dark");
    },
    cycle() {
      const i = THEMES.indexOf(this.current);
      this.set(THEMES[(i + 1) % THEMES.length]);
    },
    set(name) {
      if (!THEMES.includes(name)) return;
      this.current = name;
      document.documentElement.dataset.theme = name;
      document.body.dataset.theme = name;
      try { localStorage.setItem("theme", name); } catch (_) {}
      fetch("/admin/api/theme", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme: name }),
      }).catch(() => {});
    },
  });

  // ===== 实时时钟（PR-FE-1）=====
  Alpine.store("clock", {
    time: new Date().toTimeString().slice(0, 8),
    _started: false,
    start() {
      if (this._started) return;
      this._started = true;
      setInterval(() => {
        this.time = new Date().toTimeString().slice(0, 8);
      }, 1000);
    },
  });

  // ===== 子条 stockpile 计数（PR-FE-1 收尾）=====
  Alpine.store("substrip", {
    stockpileCount: null,
    sessionId: "SE-" + new Date().toISOString().slice(0, 10).replace(/-/g, "") +
                "-" + String(Math.floor(Date.now() / 1000) % 1000).padStart(3, "0"),
    async loadStockpile() {
      try {
        const r = await fetch("/stockpile/status");
        const j = await r.json();
        if (j.ok) this.stockpileCount = j.count;
      } catch (_) {
        /* 离线时保持 null，UI 显示 — */
      }
    },
  });
  Alpine.store("substrip").loadStockpile();

  // ===== Nav (PR-FE-1：加 collapsed / 9 模块图标 / 数字快捷键) =====
  // onFirstActivate(pageId, cb): 首次切到该 page 时触发一次 cb，后续切走再回不重复触发。
  // 用于 sa/dq 等"进页才有数据"页省去用户点刷新一步。
  Alpine.store("nav", {
    current: "dashboard",
    collapsed: false,
    _initedPages: [],
    _callbacks: {},
    pages: [
      { id: "dashboard",         label: "总览",       icon: "dashboard",  code: "00", shortcut: "`" },
      { id: "main",              label: "标签处理",   icon: "tags",       code: "01", shortcut: "1" },
      { id: "dup",               label: "标签查重",   icon: "dedupe",     code: "02", shortcut: "2" },
      { id: "purchase",          label: "采购导入",   icon: "purchase",   code: "03", shortcut: "3" },
      { id: "attendance",        label: "考勤台账",   icon: "attendance", code: "04", shortcut: "4" },
      { id: "history",           label: "货号历史",   icon: "history",    code: "05", shortcut: "5" },
      { id: "data_quality",      label: "数据质量",   icon: "quality",    code: "06", shortcut: "6" },
      { id: "inventory",         label: "数据健康",   icon: "inout",      code: "07", shortcut: "7" },
      { id: "foreign_customers", label: "老外客人",   icon: "overseas",   code: "08", shortcut: "8" },
      { id: "forecast_eval",     label: "预测效果",   icon: "sales",      code: "09", shortcut: "9" },
      // 2026-05-23: 销售分析功能已被货号历史 EXT panel + 补货决策吸收, 入口收起.
      // 独有的"等级一致性告警" / "未设标签批量管理" 是低频审计场景, 真要做可
      // 单独迁到 data_quality 页. 后端 list_sku_summary 不动 (补货决策也用),
      // 页面 DOM (pageSalesAnalytics) 留着备份, 等下周确认无人用再彻底删.
      // { id: "sales_analytics",   label: "销售分析",   icon: "sales",      code: "09", shortcut: "9" },
      { id: "restock",           label: "补货决策",   icon: "sales",      code: "11", shortcut: "" },
      { id: "pda_pending",       label: "PDA 待处理", icon: "tags",       code: "12", shortcut: "" },
      { id: "admin",             label: "系统管理",   icon: "quality",    code: "SYS", shortcut: "0" },
    ],
    get visiblePages() {
      return this.pages.filter(p => window.__IS_ADMIN || !['pda_pending', 'admin'].includes(p.id));
    },
    switch(id) {
      this.current = id;
      this._fireFirstActivate(id);
    },
    onFirstActivate(pageId, cb) {
      this._callbacks[pageId] = cb;
      // 已经是 current 但还没 init 过 → 立即触发（处理"注册晚于切页"的边界）
      if (this.current === pageId) {
        this._fireFirstActivate(pageId);
      }
    },
    _fireFirstActivate(pageId) {
      if (this._initedPages.includes(pageId)) return;
      const cb = this._callbacks[pageId];
      if (!cb) return;
      this._initedPages.push(pageId);
      try {
        cb();
      } catch (e) {
        console.error("nav lazy load callback error:", pageId, e);
      }
    },
    toggleCollapse() {
      this.collapsed = !this.collapsed;
      try {
        localStorage.setItem("nav.collapsed", this.collapsed ? "1" : "0");
      } catch (_) {
        /* ignore */
      }
    },
    initFromStorage() {
      try {
        this.collapsed = localStorage.getItem("nav.collapsed") === "1";
      } catch (_) {
        /* ignore */
      }
    },
    bySortcut(key) {
      return this.pages.find((p) => p.shortcut === key);
    },
  });
  Alpine.store("nav").initFromStorage();
});

// ===== 全局键盘快捷键（PR-FE-1）=====
// alpine:init 之外注册以确保即使 Alpine 异常仍可工作。
document.addEventListener("keydown", (e) => {
  // ⌘/Ctrl + 0-9 切 nav（0 = 第 10 项 transfer）
  if ((e.metaKey || e.ctrlKey) && /^[0-9]$/.test(e.key)) {
    const store = window.Alpine?.store?.("nav");
    if (!store) return;
    const target = store.bySortcut(e.key);
    if (target) {
      e.preventDefault();
      store.switch(target.id);
    }
  }
});
