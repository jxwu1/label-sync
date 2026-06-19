import type { ScanBatchList } from "../../api/types.gen";
import type { ScanBatchVM } from "./scan-batch-types";

export function normalizeBatches(raw: ScanBatchList): ScanBatchVM[] {
  return (raw.batches ?? []).map((b) => ({
    batchId: b.batch_id,
    employee: b.employee,
    scannedAt: b.scanned_at,
    csvFilename: b.csv_filename ?? null,
    csvRows: b.csv_rows ?? null,
    csvSizeBytes: b.csv_size_bytes ?? null,
    xlsxFiles: (b.xlsx_files ?? []).map((f) => ({ name: f.name, sizeBytes: f.size_bytes })),
  }));
}
