import type { RecentChangesBatchList, RecentChangesDetail } from "../../api/types.gen";
import type { RecentBatchVM, RecentDetailVM } from "./recent-changes-types";

export function normalizeBatches(raw: RecentChangesBatchList): RecentBatchVM[] {
  return (raw.batches ?? []).map((b) => ({
    batchId: b.batch_id,
    takenAt: b.taken_at ?? null,
    totalLocal: b.total_local ?? null,
    changeCount: b.change_count ?? 0,
    affectedBarcodes: b.affected_barcodes ?? 0,
    isOpen: b.is_open,
  }));
}

export function normalizeDetail(raw: RecentChangesDetail): RecentDetailVM {
  const s = raw.summary;
  return {
    summary: {
      locationChanges: s.location_changes ?? 0,
      modelChanges: s.model_changes ?? 0,
      inserts: s.inserts ?? 0,
      deactivates: s.deactivates ?? 0,
      reactivates: s.reactivates ?? 0,
      roundtripCount: s.roundtrip_count ?? 0,
    },
    changes: (raw.changes ?? []).map((c) => ({
      barcode: c.barcode,
      model: c.model,
      field: c.field,
      fromValue: c.from_value ?? null,
      toValue: c.to_value ?? null,
      changeType: c.change_type,
      at: c.at,
    })),
    totalCount: raw.total_count ?? 0,
  };
}
