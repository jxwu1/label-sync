import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import TimelineChart from "./TimelineChart.vue";
import type { TimelineWeekVM, MonthlySaleVM } from "./timeline-types";

function wk(p: Partial<TimelineWeekVM> & { weekStart: string }): TimelineWeekVM {
  return { saleQty: 0, purchaseUnitPrice: null, rawUnitPriceLocal: null, currencyLocal: "EUR", ...p };
}
function mo(monthStart: string, saleQty = 0, retailQty = 0): MonthlySaleVM {
  return { monthStart, saleQty, retailQty };
}

describe("TimelineChart", () => {
  it("hasData=false → 无数据占位，无柱无线", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2024-01-01" })],
      monthlySales: [mo("2024-01-01", 0, 0)],
    }});
    expect(w.text()).toContain("无数据");
    expect(w.findAll("rect").length).toBe(0);
    expect(w.find("path").exists()).toBe(false);
  });

  it("只有采购无销售 → 画折线无柱", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [
        wk({ weekStart: "2024-01-01", purchaseUnitPrice: 5, rawUnitPriceLocal: 5 }),
        wk({ weekStart: "2024-01-08" }),
      ],
      monthlySales: [mo("2024-01-01", 0, 0)],
    }});
    expect(w.text()).not.toContain("无数据");
    expect(w.find("path.tml-price-line").exists()).toBe(true);
  });

  it("只有销售无采购 → 画柱无折线", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2024-01-01" })],
      monthlySales: [mo("2024-01-01", 8, 0)],
    }});
    expect(w.findAll("rect.tml-bar").length).toBe(1);
    expect(w.find("path.tml-price-line").exists()).toBe(false);
  });

  it("负净月不产生负 height + 可命中退货标记", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2024-02-01" })],
      monthlySales: [mo("2024-02-01", -5, 0)],
    }});
    // 无负 height
    for (const r of w.findAll("rect")) {
      const h = Number(r.attributes("height") ?? "0");
      expect(h).toBeGreaterThanOrEqual(0);
    }
    const marker = w.find('[data-kind="net-return"]');
    expect(marker.exists()).toBe(true);
    expect(marker.find("title").text()).toContain("净退货");
    // 三角几何断言：底 8 × 高 6 viewBox units，x 跨度恰好 8，y 跨度恰好 6
    const d = marker.attributes("d")!;
    const pts = [...d.matchAll(/([\d.]+),([\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(8, 5);
    expect(Math.max(...ys) - Math.min(...ys)).toBeCloseTo(6, 5);
  });

  it("红队：单负净月无采购 → hasData=true 且退货标记可命中", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2024-02-01" })],
      monthlySales: [mo("2024-02-01", -3, 0)],
    }});
    expect(w.text()).not.toContain("无数据");
    expect(w.find('[data-kind="net-return"]').exists()).toBe(true);
  });

  it("两次不同进价 → path 含垂直跳变（step）", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [
        wk({ weekStart: "2024-01-01", purchaseUnitPrice: 5, rawUnitPriceLocal: 5 }),
        wk({ weekStart: "2024-02-01", purchaseUnitPrice: 8, rawUnitPriceLocal: 8 }),
      ],
      monthlySales: [mo("2024-01-01", 1, 0)],
    }});
    const d = w.find("path.tml-price-line").attributes("d")!;
    // 解析 d 的点，断言存在一对相邻点 x 近似相等而 y 不同（垂直段）
    const pts = [...d.matchAll(/[ML]\s*([\d.]+)[ ,]([\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
    let hasVertical = false;
    for (let i = 1; i < pts.length; i++) {
      if (Math.abs(pts[i][0] - pts[i - 1][0]) < 0.5 && Math.abs(pts[i][1] - pts[i - 1][1]) > 0.5) hasVertical = true;
    }
    expect(hasVertical).toBe(true);
  });

  it("同价分支 → 右轴单 tick", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [
        wk({ weekStart: "2024-01-01", purchaseUnitPrice: 5, rawUnitPriceLocal: 5 }),
        wk({ weekStart: "2024-02-01", purchaseUnitPrice: 5, rawUnitPriceLocal: 5 }),
      ],
      monthlySales: [mo("2024-01-01", 1, 0)],
    }});
    expect(w.findAll("text.tml-yr").length).toBe(1);
  });

  it("X 共享日期域：采购周落在所属月柱 X 区间内", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2025-03-10", purchaseUnitPrice: 5, rawUnitPriceLocal: 5 })],
      monthlySales: [mo("2025-02-01", 1, 0), mo("2025-03-01", 1, 0), mo("2025-04-01", 1, 0)],
    }});
    const dot = w.find("circle.tml-dot");
    expect(dot.exists()).toBe(true);
    const dotX = Number(dot.attributes("cx"));
    // 找 2025-03 柱
    const marBar = w.findAll("rect.tml-bar").find((r) => r.attributes("data-month") === "2025-03-01")!;
    const bx = Number(marBar.attributes("x"));
    const bw = Number(marBar.attributes("width"));
    expect(dotX).toBeGreaterThanOrEqual(bx);
    expect(dotX).toBeLessThanOrEqual(bx + bw);
  });

  it("单月：唯一 X 标签 text-anchor=middle", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2024-06-01" })],
      monthlySales: [mo("2024-06-01", 5, 0)],
    }});
    const labels = w.findAll("text.tml-xlabel");
    expect(labels.length).toBe(1);
    expect(labels[0].attributes("text-anchor")).toBe("middle");
  });

  it("窄容器：X 首标签 anchor=start、末标签 anchor=end，x 在 [0,W]", () => {
    const months = Array.from({ length: 12 }, (_, i) =>
      mo(`2024-${String(i + 1).padStart(2, "0")}-01`, 1, 0));
    const w = mount(TimelineChart, { props: { weeks: [wk({ weekStart: "2024-01-01" })], monthlySales: months }});
    const labels = w.findAll("text.tml-xlabel");
    expect(labels.length).toBeGreaterThanOrEqual(2);
    const first = labels[0], last = labels[labels.length - 1];
    expect(first.attributes("text-anchor")).toBe("start");
    expect(last.attributes("text-anchor")).toBe("end");
    for (const l of [first, last]) {
      const x = Number(l.attributes("x"));
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(1000);
    }
  });

  it("销量轴 maxQ 极小时左轴标签不重复", () => {
    // maxQ=1 → Math.round(1*f) for f∈[1,0.75,0.5,0.25] = [1,1,1,0] — dedup keeps [1,0]
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2024-01-01" })],
      monthlySales: [mo("2024-01-01", 1, 0)],
    }});
    const labels = w.findAll("text.tml-yl").map((el) => el.text());
    const unique = new Set(labels);
    expect(unique.size).toBe(labels.length); // no duplicate label strings
  });

  it("CN tooltip 含 ¥ 与 €", () => {
    const w = mount(TimelineChart, { props: {
      weeks: [wk({ weekStart: "2024-01-01", purchaseUnitPrice: 5.4, rawUnitPriceLocal: 42, currencyLocal: "RMB" })],
      monthlySales: [mo("2024-01-01", 1, 0)],
    }});
    const t = w.find("circle.tml-dot title").text();
    expect(t).toContain("¥");
    expect(t).toContain("€");
  });
});
