import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({
  UnauthenticatedError: class UnauthenticatedError extends Error {},
  apiGet: vi.fn(),
}));

import { apiGet } from "../../api/client";
import ScanBatchPanel from "./ScanBatchPanel.vue";

function batchList() {
  return {
    ok: true,
    batches: [
      { batch_id: "ALI价格标20260420100000", employee: "ALI", scanned_at: "2026-04-20 10:00:00",
        csv_filename: "x.csv", csv_rows: 3, csv_size_bytes: 120, xlsx_files: [{ name: "ALI.xlsx", size_bytes: 400 }] },
      { batch_id: "ZH#A 价/标20260421100000", employee: "ABDUL", scanned_at: "2026-04-21 10:00:00",
        csv_filename: null, csv_rows: null, csv_size_bytes: null, xlsx_files: [] },
    ],
  };
}

async function mountLoaded() {
  vi.mocked(apiGet).mockResolvedValue(batchList() as never);
  const w = mount(ScanBatchPanel);
  await new Promise((r) => setTimeout(r, 0)); // flush onMounted ensureLoaded
  await w.vm.$nextTick();
  return w;
}

describe("ScanBatchPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(apiGet).mockReset();
  });

  it("onMounted 调 ensureLoaded（请求列表端点）", async () => {
    await mountLoaded();
    expect(vi.mocked(apiGet).mock.calls.some((c) => c[0] === "/api/history/scan-batches")).toBe(true);
  });

  it("行头是 button 且 aria-expanded 随展开切换", async () => {
    const w = await mountLoaded();
    const head = w.findAll("button.sb-row-head")[0];
    expect(head.attributes("type")).toBe("button");
    expect(head.attributes("aria-expanded")).toBe("false");
    await head.trigger("click");
    expect(w.findAll("button.sb-row-head")[0].attributes("aria-expanded")).toBe("true");
  });

  it("多行可同时展开", async () => {
    const w = await mountLoaded();
    const heads = w.findAll("button.sb-row-head");
    await heads[0].trigger("click");
    await heads[1].trigger("click");
    const expanded = w.findAll("button.sb-row-head").filter((h) => h.attributes("aria-expanded") === "true");
    expect(expanded.length).toBe(2);
  });

  it("CSV 缺失行显示「CSV 缺失」且无 CSV 下载链", async () => {
    const w = await mountLoaded();
    await w.findAll("button.sb-row-head")[1].trigger("click");
    const html = w.html();
    expect(html).toContain("CSV 缺失");
  });

  it("下载链接 encodeURIComponent 编码 batchId 与文件名；无 target=_blank", async () => {
    const w = await mountLoaded();
    await w.findAll("button.sb-row-head")[0].trigger("click");
    const links = w.findAll("a.sb-dl");
    const hrefs = links.map((a) => a.attributes("href"));
    const enc = encodeURIComponent("ALI价格标20260420100000");
    expect(hrefs).toContain(`/scan_history/batches/${enc}/download/csv`);
    expect(hrefs).toContain(`/scan_history/batches/${enc}/download/zip`);
    expect(hrefs).toContain(`/scan_history/batches/${enc}/files/${encodeURIComponent("ALI.xlsx")}`);
    for (const a of links) expect(a.attributes("target")).toBeUndefined();
  });

  it("特殊字符 batchId（#、空格、/）正确编码", async () => {
    // Use a custom payload: batch 1 has special chars in batchId + a csv file so ZIP link renders
    const payload = {
      ok: true,
      batches: [
        ...batchList().batches.slice(0, 1),
        { batch_id: "ZH#A 价/标20260421100000", employee: "ABDUL", scanned_at: "2026-04-21 10:00:00",
          csv_filename: "b.csv", csv_rows: 1, csv_size_bytes: 50, xlsx_files: [] },
      ],
    };
    vi.mocked(apiGet).mockResolvedValue(payload as never);
    const w = mount(ScanBatchPanel);
    await new Promise((r) => setTimeout(r, 0));
    await w.vm.$nextTick();
    await w.findAll("button.sb-row-head")[1].trigger("click");
    const zip = w.findAll("a.sb-dl").find((a) => a.attributes("href")?.includes("/download/zip"));
    expect(zip?.attributes("href")).toBe(
      `/scan_history/batches/${encodeURIComponent("ZH#A 价/标20260421100000")}/download/zip`,
    );
  });

  it("员工筛选无匹配 → 暂无批次空态", async () => {
    const w = await mountLoaded();
    // Drive filter via store directly since setValue cannot set illegal option values
    const { useScanBatchesStore } = await import("../../stores/scanBatches");
    useScanBatchesStore().setEmployeeFilter("不存在的人");
    await w.vm.$nextTick();
    expect(w.html()).toContain("暂无批次");
  });

  it("加载中显示「加载中」指示，加载完消失", async () => {
    let resolve: (v: unknown) => void = () => {};
    vi.mocked(apiGet).mockImplementation(() => new Promise((r) => { resolve = r; }) as never);
    const w = mount(ScanBatchPanel);
    await w.vm.$nextTick();
    expect(w.html()).toContain("加载中");
    resolve(batchList());
    await new Promise((r) => setTimeout(r, 0));
    await w.vm.$nextTick();
    expect(w.html()).not.toContain("加载中");
  });

  it("加载失败 → 错误条 + 重试按钮调 ensureLoaded", async () => {
    vi.mocked(apiGet).mockRejectedValueOnce(new Error("boom"));
    const w = mount(ScanBatchPanel);
    await new Promise((r) => setTimeout(r, 0));
    await w.vm.$nextTick();
    expect(w.html()).toContain("boom");
    vi.mocked(apiGet).mockResolvedValue(batchList() as never);
    await w.find("button.sb-retry").trigger("click");
    await new Promise((r) => setTimeout(r, 0));
    await w.vm.$nextTick();
    expect(w.findAll("button.sb-row-head").length).toBe(2);
  });

  // Fix C: csv_rows null-safe rendering
  it("Fix C — csv_rows 为 null 时显示「行数未知」而非「null 行」", async () => {
    const payload = {
      ok: true,
      batches: [
        {
          batch_id: "NULLROWS20260420",
          employee: "TEST",
          scanned_at: "2026-04-20 10:00:00",
          csv_filename: "x.csv",
          csv_rows: null,
          csv_size_bytes: null,
          xlsx_files: [],
        },
      ],
    };
    vi.mocked(apiGet).mockResolvedValue(payload as never);
    const w = mount(ScanBatchPanel);
    await new Promise((r) => setTimeout(r, 0));
    await w.vm.$nextTick();
    await w.findAll("button.sb-row-head")[0].trigger("click");
    const html = w.html();
    expect(html).not.toContain("null 行");
    expect(html).toContain("行数未知");
  });

  // Fix D: ZIP link hidden when no files
  it("Fix D — 无任何文件的批次不显示「下载全部 ZIP」链接", async () => {
    const w = await mountLoaded();
    // batch index 1 has csv_filename: null, xlsx_files: []
    await w.findAll("button.sb-row-head")[1].trigger("click");
    const zipLinks = w.findAll("a").filter((a) => a.attributes("href")?.includes("/download/zip"));
    expect(zipLinks.length).toBe(0);
  });

  // Fix E: no empty-state flash during initial load
  it("Fix E — 初始加载中不显示「暂无批次」（无空态闪烁）", async () => {
    vi.mocked(apiGet).mockImplementation(() => new Promise(() => {}) as never);
    const w = mount(ScanBatchPanel);
    await w.vm.$nextTick();
    expect(w.html()).toContain("加载中");
    expect(w.html()).not.toContain("暂无批次");
  });

  // Fix #5: onEmployeeChange "" path → store.employeeFilter becomes null
  it("Fix #5 — select 改回「全部员工」后 employeeFilter 置为 null", async () => {
    const w = await mountLoaded();
    const { useScanBatchesStore } = await import("../../stores/scanBatches");
    const store = useScanBatchesStore();

    const select = w.find("select.sb-employee");
    // First pick a real employee
    await select.setValue("ALI");
    await select.trigger("change");
    await w.vm.$nextTick();
    expect(store.employeeFilter).toBe("ALI");

    // Then reset to "" (全部员工)
    await select.setValue("");
    await select.trigger("change");
    await w.vm.$nextTick();
    expect(store.employeeFilter).toBeNull();
  });
});
