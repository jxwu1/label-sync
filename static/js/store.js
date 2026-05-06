// Alpine stores — 阶段 2 SSOT
// 所有跨页 UI 状态都集中在这里。遗留模块直接调 Alpine.store('xxx').yyy(...)
"use strict";

document.addEventListener("alpine:init", () => {
  // 终端日志
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

  // 全局 badge / status
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

  // 待上传文件
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

  // 浮层 / 红点
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

  // 跨端消息
  Alpine.store("messages", {
    list: [],
    setList(items) {
      this.list = items;
    },
  });

  // 互传文件列表
  Alpine.store("transfer", {
    files: [],
    setFiles(items) {
      this.files = items;
    },
  });

  // Nav (PR2 才会被模板消费；PR1 阶段提前注册让形状稳定)
  Alpine.store("nav", {
    current: "main",
    pages: [
      { id: "main",         label: "标签",     icon: "📋" },
      { id: "dup",          label: "查重",     icon: "🔍" },
      { id: "purchase",     label: "采购",     icon: "📦" },
      { id: "attendance",   label: "考勤",     icon: "🕐" },
      { id: "history",      label: "货号历史", icon: "📜" },
      { id: "data_quality", label: "数据质量", icon: "🔍" },
      { id: "inventory",    label: "进销存导入", icon: "📥" },
      { id: "foreign_customers", label: "老外客人", icon: "🌍" },
      { id: "sales_analytics", label: "销售分析", icon: "📊" },
    ],
    switch(id) {
      this.current = id;
    },
  });
});
