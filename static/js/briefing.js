// 最新批次简报: 首次切到该页时拉 /briefing/data 填充。
function briefingPage() {
  return {
    data: null,
    error: null,
    card(key) {
      return this.data?.cards?.[key];
    },
    action(key) {
      return this.data?.actions?.[key];
    },
    // 销售健康主卡状态: 好于上批=good / 差于上批=warn / 覆盖不足或周未完整=neutral / 取数失败=danger
    heroStatus() {
      const c = this.card("sales_health");
      if (!c) return "neutral";
      if (!c.ok) return "danger";
      if (c.status === "ok") return c.delta_pct >= 0 ? "good" : "warn";
      return "neutral";
    },
    // 风险卡状态色: 取数失败=danger; 否则按风险量
    riskStatus(key) {
      const c = this.card(key);
      if (!c) return "neutral";
      if (!c.ok) return "danger";
      if (key === "restock_risk") {
        if ((c.urgent || 0) > 0) return "danger";
        return (c.total || 0) > 0 ? "warn" : "good";
      }
      if (key === "data_health") return c.stale ? "danger" : "good";
      // stockout_impact / overstock_risk: 有命中=warn, 0=good
      return (c.total || 0) > 0 ? "warn" : "good";
    },
    fmtGenTime() {
      return (this.data?.generated_at || "").replace("T", " ").slice(11, 16);
    },
    init() {
      const store = window.Alpine?.store?.("nav");
      if (store) {
        store.onFirstActivate("briefing", () => this.load());
      } else {
        this.load();
      }
    },
    async load() {
      this.error = null;
      try {
        const resp = await fetch("/briefing/data");
        if (!resp.ok) {
          this.error = `服务返回 ${resp.status}`;
          return;
        }
        this.data = await resp.json();
      } catch (e) {
        this.error = "网络错误，请稍后重试";
        console.error("briefing load failed", e);
      }
    },
  };
}
window.briefingPage = briefingPage;
