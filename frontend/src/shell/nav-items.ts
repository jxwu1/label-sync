export interface NavItem {
  id: string;
  label: string;
  icon: string; // sprite symbol 名 → #icon-<icon>
  code: string;
  routeName?: string; // 已迁 → vue-router route name
  legacyPageId?: string; // 未迁 → 旧 SPA /?page=<id>
  requiresAdmin?: boolean;
}

// 简报已迁(routeName)；13 个模块页未迁(legacyPageId)。顺序对齐旧侧栏。
export const NAV_ITEMS: NavItem[] = [
  { id: "briefing", label: "最新批次简报", icon: "dashboard", code: "00", routeName: "briefing" },
  { id: "dashboard", label: "总览", icon: "dashboard", code: "00", legacyPageId: "dashboard" },
  { id: "main", label: "标签处理", icon: "tags", code: "01", legacyPageId: "main" },
  { id: "dup", label: "标签查重", icon: "dedupe", code: "02", legacyPageId: "dup" },
  { id: "purchase", label: "采购导入", icon: "purchase", code: "03", legacyPageId: "purchase" },
  { id: "attendance", label: "考勤台账", icon: "attendance", code: "04", legacyPageId: "attendance" },
  { id: "history", label: "货号历史", icon: "history", code: "05", legacyPageId: "history" },
  { id: "data_quality", label: "数据质量", icon: "quality", code: "06", legacyPageId: "data_quality" },
  { id: "inventory", label: "数据健康", icon: "inout", code: "07", legacyPageId: "inventory" },
  { id: "foreign_customers", label: "老外客人", icon: "overseas", code: "08", legacyPageId: "foreign_customers" },
  { id: "forecast_eval", label: "预测效果", icon: "sales", code: "09", routeName: "forecast-eval" },
  { id: "restock", label: "补货决策", icon: "sales", code: "11", legacyPageId: "restock" },
  { id: "pda_pending", label: "PDA 待处理", icon: "tags", code: "12", legacyPageId: "pda_pending", requiresAdmin: true },
  { id: "admin", label: "系统管理", icon: "quality", code: "SYS", legacyPageId: "admin", requiresAdmin: true },
];

// sprite 里有的 symbol 名（IconSprite.vue 同源，测试用）。
export const SPRITE_ICONS = [
  "dashboard", "tags", "dedupe", "purchase", "attendance", "history",
  "quality", "inout", "overseas", "sales", "transfer",
];
