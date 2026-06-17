import { describe, expect, it } from "vitest";
import type { HistorySearchData } from "../../api/types.gen";
import { normalizeHistory } from "./normalize";

describe("normalizeHistory", () => {
  it("found=false 无候选 → notfound", () => {
    const r = normalizeHistory({ ok: true, found: false } as HistorySearchData);
    expect(r.kind).toBe("notfound");
  });

  it("found=false 有候选 → fuzzy", () => {
    const r = normalizeHistory({
      ok: true, found: false,
      fuzzy_matches: [{ barcode: "B1", model: "M1", location: "A22", is_active: true }],
    } as HistorySearchData);
    expect(r.kind).toBe("fuzzy");
    if (r.kind === "fuzzy") {
      expect(r.matches[0].barcode).toBe("B1");
      expect(r.matches[0].isActive).toBe(true);
    }
  });

  it("found=true → hit，含库位 split 事件 + inventory summary 事件 + camelCase", () => {
    const r = normalizeHistory({
      ok: true, found: true,
      current: {
        barcode: "B1", model: "M1", location: "A22", is_active: true,
        source: "scan_import", created_at: "2026-01-01", updated_at: "2026-06-01",
        product_name_zh: "中文名", product_name_local: "local", erp_category_raw: "x",
        erp_category_code: "y", manual_grade: 8, stock_price: null, sale_price: 12.5,
        is_truly_discontinued: false,
        store_locations: ["A22"], warehouse_locations: ["X11"], unknown_locations: [],
      },
      events: [
        { at: "2026-04-25 16:52:43", change_type: "update", source: "scan_import", summary: null,
          changes: [{ field: "stockpile_location", old: "A22", new: "A22/X11",
            old_split: { stores: ["A22"], warehouses: [], unknown: [] },
            new_split: { stores: ["A22"], warehouses: ["X11"], unknown: [] } }] },
        { at: "2026-03-01", change_type: "sale", source: "inventory_events",
          summary: "销售 5 件 × €12.50（C001）", changes: [] },
      ],
    } as HistorySearchData);
    expect(r.kind).toBe("hit");
    if (r.kind === "hit") {
      expect(r.current.productNameZh).toBe("中文名");
      expect(r.current.manualGrade).toBe(8);
      expect(r.current.salePrice).toBe(12.5);
      expect(r.current.storeLocations).toEqual(["A22"]);
      expect(r.events[0].changes[0].newSplit?.warehouses).toEqual(["X11"]);
      expect(r.events[1].summary).toContain("销售 5 件");
      expect(r.events[1].changes).toEqual([]);
    }
  });

  it("found=true events 缺省 → hit events 为 []", () => {
    const r = normalizeHistory({
      ok: true, found: true,
      current: {
        barcode: "B1", model: "M1", location: "", is_active: true, source: null,
        created_at: null, updated_at: null, product_name_zh: null, product_name_local: null,
        erp_category_raw: null, erp_category_code: null, manual_grade: null,
        stock_price: null, sale_price: null, is_truly_discontinued: true,
        store_locations: [], warehouse_locations: [], unknown_locations: [],
      },
    } as HistorySearchData);
    expect(r.kind).toBe("hit");
    if (r.kind === "hit") expect(r.events).toEqual([]);
  });
});
