import { describe, it, expect } from "vitest";
import { normalizeBatches, normalizeDetail } from "./recent-changes-normalize";
import type { RecentChangesBatchList, RecentChangesDetail } from "../../api/types.gen";

describe("normalizeBatches", () => {
  it("maps snake to camel for a closed batch", () => {
    const raw: RecentChangesBatchList = {
      ok: true,
      batches: [
        {
          batch_id: 42,
          taken_at: "2024-01-01T10:00:00",
          total_local: 1234,
          change_count: 7,
          affected_barcodes: 5,
          is_open: false,
        },
      ],
    };
    const vm = normalizeBatches(raw);
    expect(vm).toHaveLength(1);
    expect(vm[0].batchId).toBe(42);
    expect(vm[0].takenAt).toBe("2024-01-01T10:00:00");
    expect(vm[0].totalLocal).toBe(1234);
    expect(vm[0].changeCount).toBe(7);
    expect(vm[0].affectedBarcodes).toBe(5);
    expect(vm[0].isOpen).toBe(false);
  });

  it("passes through nulls for an open batch", () => {
    const raw: RecentChangesBatchList = {
      ok: true,
      batches: [
        {
          batch_id: 99,
          taken_at: null,
          total_local: null,
          change_count: 0,
          affected_barcodes: 0,
          is_open: true,
        },
      ],
    };
    const vm = normalizeBatches(raw);
    expect(vm[0].takenAt).toBeNull();
    expect(vm[0].totalLocal).toBeNull();
    expect(vm[0].isOpen).toBe(true);
  });

  it("returns [] when batches missing", () => {
    const raw = { ok: true } as unknown as RecentChangesBatchList;
    expect(normalizeBatches(raw)).toEqual([]);
  });
});

describe("normalizeDetail", () => {
  it("maps summary, changes and totalCount", () => {
    const raw: RecentChangesDetail = {
      ok: true,
      summary: {
        location_changes: 3,
        model_changes: 2,
        inserts: 1,
        deactivates: 4,
        reactivates: 5,
        roundtrip_count: 6,
      },
      changes: [
        {
          barcode: "ABC123",
          model: "M1",
          field: "location",
          from_value: "A1",
          to_value: "B2",
          change_type: "location_change",
          at: "2024-01-01T10:00:00",
        },
      ],
      total_count: 1,
    };
    const vm = normalizeDetail(raw);
    expect(vm.summary.locationChanges).toBe(3);
    expect(vm.summary.modelChanges).toBe(2);
    expect(vm.summary.inserts).toBe(1);
    expect(vm.summary.deactivates).toBe(4);
    expect(vm.summary.reactivates).toBe(5);
    expect(vm.summary.roundtripCount).toBe(6);
    expect(vm.changes).toHaveLength(1);
    expect(vm.changes[0].barcode).toBe("ABC123");
    expect(vm.changes[0].fromValue).toBe("A1");
    expect(vm.changes[0].toValue).toBe("B2");
    expect(vm.changes[0].changeType).toBe("location_change");
    expect(vm.changes[0].at).toBe("2024-01-01T10:00:00");
    expect(vm.totalCount).toBe(1);
  });

  it("passes through null from_value/to_value", () => {
    const raw: RecentChangesDetail = {
      ok: true,
      summary: {
        location_changes: 0,
        model_changes: 0,
        inserts: 1,
        deactivates: 0,
        reactivates: 0,
        roundtrip_count: 0,
      },
      changes: [
        {
          barcode: "NEW1",
          model: "M2",
          field: "insert",
          from_value: null,
          to_value: null,
          change_type: "insert",
          at: "2024-01-02T08:00:00",
        },
      ],
      total_count: 1,
    };
    const vm = normalizeDetail(raw);
    expect(vm.changes[0].fromValue).toBeNull();
    expect(vm.changes[0].toValue).toBeNull();
  });

  it("returns [] changes when changes missing", () => {
    const raw = {
      ok: true,
      summary: {
        location_changes: 0,
        model_changes: 0,
        inserts: 0,
        deactivates: 0,
        reactivates: 0,
        roundtrip_count: 0,
      },
      total_count: 0,
    } as unknown as RecentChangesDetail;
    const vm = normalizeDetail(raw);
    expect(vm.changes).toEqual([]);
    expect(vm.totalCount).toBe(0);
  });
});
