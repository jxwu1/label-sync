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
    badgeText: "空闲",
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

  // ===== 待上传文件 =====
  Alpine.store("upload", {
    selected: [],
    add(files) {
      this.selected.push(...files);
    },
    remove(i) {
      this.selected.splice(i, 1);
    },
    clear() {
      this.selected = [];
    },
  });

  // ===== 浮层 / 红点 =====
  Alpine.store("ui", {
    termDrawer: false,
    transferDrawer: false,
    quickMenu: false,
    transferDot: false,
    quickTransferDot: false,
    toggleTerm() {
      this.termDrawer = !this.termDrawer;
    },
    toggleTransfer() {
      this.transferDrawer = !this.transferDrawer;
      this.transferDot = false;
      this.quickTransferDot = false;
    },
    toggleQuick() {
      this.quickMenu = !this.quickMenu;
    },
    closeQuick() {
      this.quickMenu = false;
    },
    closeTerm() {
      this.termDrawer = false;
    },
    closeTransfer() {
      this.transferDrawer = false;
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

  // ===== 主题（PR-FE-1）=====
  // FOUC 防御：index.html <head> inline script 已经设置 body.dataset.theme，
  // 这里只负责响应式切换 + localStorage 持久化
  Alpine.store("theme", {
    current: document.body.dataset.theme || "dark",
    toggle() {
      this.current = this.current === "dark" ? "light" : "dark";
      document.body.dataset.theme = this.current;
      try {
        localStorage.setItem("theme", this.current);
      } catch (_) {
        /* localStorage 可能被禁用 */
      }
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
  Alpine.store("nav", {
    current: "main",
    collapsed: false,
    pages: [
      { id: "main",              label: "标签处理",   icon: "tags",       code: "01", shortcut: "1" },
      { id: "dup",               label: "标签查重",   icon: "dedupe",     code: "02", shortcut: "2" },
      { id: "purchase",          label: "采购导入",   icon: "purchase",   code: "03", shortcut: "3" },
      { id: "attendance",        label: "考勤台账",   icon: "attendance", code: "04", shortcut: "4" },
      { id: "history",           label: "货号历史",   icon: "history",    code: "05", shortcut: "5" },
      { id: "data_quality",      label: "数据质量",   icon: "quality",    code: "06", shortcut: "6" },
      { id: "inventory",         label: "进销存导入", icon: "inout",      code: "07", shortcut: "7" },
      { id: "foreign_customers", label: "老外客人",   icon: "overseas",   code: "08", shortcut: "8" },
      { id: "sales_analytics",   label: "销售分析",   icon: "sales",      code: "09", shortcut: "9" },
    ],
    switch(id) {
      this.current = id;
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
  // ⌘/Ctrl + 1-9 切 nav
  if ((e.metaKey || e.ctrlKey) && /^[1-9]$/.test(e.key)) {
    const store = window.Alpine?.store?.("nav");
    if (!store) return;
    const target = store.bySortcut(e.key);
    if (target) {
      e.preventDefault();
      store.switch(target.id);
    }
  }
});
