import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { RecentBatchVM, RecentSummaryVM, ChangeRowVM } from "./recent-changes-types";

const state = {
  batches: [] as RecentBatchVM[],
  selectedBatchId: null as number | null,
  summary: null as RecentSummaryVM | null,
  changes: [] as ChangeRowVM[],
  totalCount: 0,
  mode: "collapsed" as "collapsed" | "raw",
  filter: { field: null as string | null, changeType: null as string | null },
  loading: false,
  error: null as string | null,
  detailLoading: false,
  detailError: null as string | null,
  loaded: false,
  ensureLoaded: vi.fn(),
  loadDetail: vi.fn(),
  selectBatch: vi.fn(),
  setMode: vi.fn(),
  setFilter: vi.fn(),
};
vi.mock("../../stores/recentChanges", () => ({ useRecentChangesStore: () => state }));

import RecentChangesPanel from "./RecentChangesPanel.vue";

function reset() {
  state.batches = [];
  state.selectedBatchId = null;
  state.summary = null;
  state.changes = [];
  state.totalCount = 0;
  state.mode = "collapsed";
  state.filter = { field: null, changeType: null };
  state.loading = false;
  state.error = null;
  state.detailLoading = false;
  state.detailError = null;
  state.loaded = false;
  state.ensureLoaded = vi.fn();
  state.loadDetail = vi.fn();
  state.selectBatch = vi.fn();
  state.setMode = vi.fn();
  state.setFilter = vi.fn();
}

function aBatch(over: Partial<RecentBatchVM> = {}): RecentBatchVM {
  return { batchId: 1, takenAt: "2026-06-01 14:30:00", totalLocal: 120, changeCount: 8, affectedBarcodes: 5, isOpen: false, ...over };
}
function aSummary(over: Partial<RecentSummaryVM> = {}): RecentSummaryVM {
  return { locationChanges: 2, modelChanges: 1, inserts: 3, deactivates: 1, reactivates: 1, roundtripCount: 4, ...over };
}
function aChange(over: Partial<ChangeRowVM> = {}): ChangeRowVM {
  return { barcode: "B1", model: "M1", field: "stockpile_location", fromValue: "A22", toValue: "X11", changeType: "update", at: "2026-06-01 14:30:45", ...over };
}

describe("RecentChangesPanel", () => {
  it("onMounted → store.ensureLoaded 调用", () => {
    reset();
    mount(RecentChangesPanel);
    expect(state.ensureLoaded).toHaveBeenCalled();
  });

  it("batches loading 态 → 「批次加载中…」", () => {
    reset(); state.loading = true;
    expect(mount(RecentChangesPanel).text()).toContain("批次加载中");
  });

  it("batches error 态 → 错误条 + 重试 button，点击调 ensureLoaded", async () => {
    reset(); state.error = "API 500: batches";
    const w = mount(RecentChangesPanel);
    expect(w.text()).toContain("API 500");
    const btn = w.findAll("button").find((b) => b.text() === "重试");
    expect(btn).toBeTruthy();
    await btn!.trigger("click");
    // mounted call + retry call
    expect(state.ensureLoaded).toHaveBeenCalledTimes(2);
  });

  it("loaded 且 batches 空 → 「还没有 import 记录」", () => {
    reset(); state.loaded = true; state.batches = [];
    expect(mount(RecentChangesPanel).text()).toContain("还没有 import 记录");
  });

  it("batch dropdown：开放批次显示「🔄 进行中」文案", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch({ batchId: 9, isOpen: true, affectedBarcodes: 7, takenAt: "2026-06-02 09:00:00" })];
    state.selectedBatchId = 9;
    state.summary = aSummary();
    const w = mount(RecentChangesPanel);
    const opt = w.find("select option");
    expect(opt.text()).toContain("🔄 进行中（上次 import 之后）");
    expect(opt.text()).toContain("改动 7 个货号");
    expect(opt.text()).toContain("2026-06-02 09:00:00");
  });

  it("batch dropdown：关闭批次显示「{takenAt}（{totalLocal} 条 / 改动 {affectedBarcodes} 个货号）」", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch({ batchId: 3, isOpen: false, takenAt: "2026-05-30 10:00:00", totalLocal: 200, affectedBarcodes: 12 })];
    state.selectedBatchId = 3;
    state.summary = aSummary();
    const w = mount(RecentChangesPanel);
    const opt = w.find("select option");
    expect(opt.text()).toContain("2026-05-30 10:00:00");
    expect(opt.text()).toContain("200 条");
    expect(opt.text()).toContain("改动 12 个货号");
  });

  it("batch dropdown @change → store.selectBatch(Number(value))", async () => {
    reset(); state.loaded = true;
    state.batches = [aBatch({ batchId: 3 }), aBatch({ batchId: 7, takenAt: "2026-05-29 10:00:00" })];
    state.selectedBatchId = 3;
    state.summary = aSummary();
    const w = mount(RecentChangesPanel);
    await w.find("select").setValue("7");
    expect(state.selectBatch).toHaveBeenCalledWith(7);
  });

  it("5 stat boxes（库位/型号/新增/失效/重新上架）+ roundtrip 备注", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    const w = mount(RecentChangesPanel);
    const boxes = w.findAll("button.rc-stat");
    expect(boxes.length).toBe(5);
    const t = w.text();
    expect(t).toContain("库位变更");
    expect(t).toContain("型号变更");
    expect(t).toContain("新增");
    expect(t).toContain("失效");
    expect(t).toContain("重新上架");
    expect(t).toContain("来回波动");
    expect(t).toContain("4"); // roundtripCount
  });

  it("stat box 点击 → store.setFilter（库位 → field stockpile_location）", async () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    const w = mount(RecentChangesPanel);
    const boxes = w.findAll("button.rc-stat");
    await boxes[0].trigger("click"); // 库位变更
    expect(state.setFilter).toHaveBeenCalledWith({ field: "stockpile_location", changeType: null });
  });

  it("stat box 点击 → 新增 → change_type insert", async () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    const w = mount(RecentChangesPanel);
    const boxes = w.findAll("button.rc-stat");
    await boxes[2].trigger("click"); // 新增
    expect(state.setFilter).toHaveBeenCalledWith({ field: null, changeType: "insert" });
  });

  it("filter chips（collapsed 5 个）+ 点击 → store.setFilter", async () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    const w = mount(RecentChangesPanel);
    const chips = w.findAll("button.rc-chip");
    expect(chips.length).toBe(5);
    expect(w.text()).toContain("全部");
    expect(w.text()).toContain("仅库位");
    await chips[1].trigger("click"); // 仅库位
    expect(state.setFilter).toHaveBeenCalledWith({ field: "stockpile_location", changeType: null });
  });

  it("raw 模式额外 2 个 chip（共 7）", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    state.mode = "raw";
    const w = mount(RecentChangesPanel);
    expect(w.findAll("button.rc-chip").length).toBe(7);
  });

  it("mode toggle button → store.setMode", async () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    const w = mount(RecentChangesPanel);
    const btn = w.find("button.rc-mode-toggle");
    expect(btn.exists()).toBe(true);
    await btn.trigger("click"); // collapsed → raw
    expect(state.setMode).toHaveBeenCalledWith("raw");
  });

  it("collapsed 列表：4 列表头（货号/型号/变化/时间）", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    state.changes = [aChange()];
    const w = mount(RecentChangesPanel);
    const ths = w.findAll("table.rc-tbl thead th");
    expect(ths.length).toBe(4);
    expect(ths.map((t) => t.text())).toEqual(["货号", "型号", "变化", "时间"]);
  });

  it("collapsed 变化 cell：库位 from → to", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    state.changes = [aChange({ field: "stockpile_location", fromValue: "A22", toValue: "X11", changeType: "update" })];
    const w = mount(RecentChangesPanel);
    const cell = w.find("td .rc-change-loc");
    expect(cell.exists()).toBe(true);
    expect(cell.text()).toContain("库位");
    expect(cell.text()).toContain("A22");
    expect(cell.text()).toContain("X11");
    expect(cell.find(".rc-change-to--loc").exists()).toBe(true);
  });

  it("collapsed 变化 cell：型号 from → to", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    state.changes = [aChange({ field: "product_model", fromValue: "OLD", toValue: "NEW", changeType: "update" })];
    const w = mount(RecentChangesPanel);
    const cell = w.find("td .rc-change-model");
    expect(cell.exists()).toBe(true);
    expect(cell.text()).toContain("型号");
    expect(cell.find(".rc-change-to--model").exists()).toBe(true);
  });

  it("collapsed 变化 cell：insert tag", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    state.changes = [aChange({ changeType: "insert", toValue: "B999", barcode: "B999" })];
    const w = mount(RecentChangesPanel);
    expect(w.find(".rc-tag--insert").exists()).toBe(true);
    expect(w.text()).toContain("新货号");
    expect(w.text()).toContain("B999");
  });

  it("collapsed 变化 cell：deactivate tag", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    state.changes = [aChange({ changeType: "deactivate" })];
    const w = mount(RecentChangesPanel);
    expect(w.find(".rc-tag--del").exists()).toBe(true);
    expect(w.text()).toContain("失效");
  });

  it("collapsed 变化 cell：reactivate tag", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    state.changes = [aChange({ changeType: "reactivate" })];
    const w = mount(RecentChangesPanel);
    expect(w.find(".rc-tag--ok").exists()).toBe(true);
    expect(w.text()).toContain("重新上架");
  });

  it("raw 列表：7 列表头", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    state.mode = "raw";
    state.changes = [aChange({ field: "stockpile_location", fromValue: "A22", toValue: "X11", changeType: "update" })];
    const w = mount(RecentChangesPanel);
    const ths = w.findAll("table.rc-tbl thead th");
    expect(ths.length).toBe(7);
    expect(ths.map((t) => t.text())).toEqual(["货号", "型号", "字段", "旧值", "新值", "类型", "时间"]);
    // 库位 field label + old/new values
    const t = w.text();
    expect(t).toContain("库位");
    expect(t).toContain("A22");
    expect(t).toContain("X11");
    expect(t).toContain("更新"); // change type CN
  });

  it("cap：changes 截断到 300 行 + 「仅显示前 300 / 共 N 条」备注（totalCount>300）", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    state.changes = Array.from({ length: 350 }, (_, i) => aChange({ barcode: `B${i}` }));
    state.totalCount = 5000;
    const w = mount(RecentChangesPanel);
    expect(w.findAll("table.rc-tbl tbody tr").length).toBe(300);
    expect(w.text()).toContain("仅显示前 300");
    expect(w.text()).toContain("共");
  });

  it("cap：totalCount<=300 不显示备注", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    state.changes = [aChange(), aChange({ barcode: "B2" })];
    state.totalCount = 2;
    const w = mount(RecentChangesPanel);
    expect(w.text()).not.toContain("仅显示前 300");
  });

  it("row 点击 → emit('drill', barcode)", async () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    state.changes = [aChange({ barcode: "DRILL1" })];
    const w = mount(RecentChangesPanel);
    await w.find("tr.rc-row").trigger("click");
    expect(w.emitted("drill")).toBeTruthy();
    expect(w.emitted("drill")![0]).toEqual(["DRILL1"]);
  });

  it("detail empty → 「该批次无实质变更」", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.summary = aSummary();
    state.changes = [];
    state.totalCount = 0;
    expect(mount(RecentChangesPanel).text()).toContain("该批次无实质变更");
  });

  it("detail loading → 「加载中」", () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.detailLoading = true;
    expect(mount(RecentChangesPanel).text()).toContain("加载中");
  });

  it("detail error → 「重试当前批次」button，点击调 loadDetail", async () => {
    reset(); state.loaded = true;
    state.batches = [aBatch()]; state.selectedBatchId = 1;
    state.detailError = "API 500: changes";
    const w = mount(RecentChangesPanel);
    expect(w.text()).toContain("API 500");
    const btn = w.findAll("button").find((b) => b.text() === "重试当前批次");
    expect(btn).toBeTruthy();
    await btn!.trigger("click");
    expect(state.loadDetail).toHaveBeenCalled();
  });
});
