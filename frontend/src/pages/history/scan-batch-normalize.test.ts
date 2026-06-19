import { describe, expect, it } from "vitest";
import { normalizeBatches } from "./scan-batch-normalize";

function raw(over = {}) {
  return {
    ok: true,
    batches: [
      {
        batch_id: "ALI价格标20260420100000",
        employee: "ALI",
        scanned_at: "2026-04-20 10:00:00",
        csv_filename: "1产品信息导入模板.csv",
        csv_rows: 3,
        csv_size_bytes: 120,
        xlsx_files: [{ name: "ALI.xlsx", size_bytes: 400 }],
        ...over,
      },
    ],
  };
}

describe("scan-batch normalize", () => {
  it("snake → camel，字段完整", () => {
    const vm = normalizeBatches(raw() as never);
    expect(vm[0]).toEqual({
      batchId: "ALI价格标20260420100000",
      employee: "ALI",
      scannedAt: "2026-04-20 10:00:00",
      csvFilename: "1产品信息导入模板.csv",
      csvRows: 3,
      csvSizeBytes: 120,
      xlsxFiles: [{ name: "ALI.xlsx", sizeBytes: 400 }],
    });
  });

  it("CSV 缺失：三字段保持 null（不塌成 0）", () => {
    const vm = normalizeBatches(
      raw({ csv_filename: null, csv_rows: null, csv_size_bytes: null }) as never,
    );
    expect(vm[0].csvFilename).toBeNull();
    expect(vm[0].csvRows).toBeNull();
    expect(vm[0].csvSizeBytes).toBeNull();
  });

  it("batches 缺省 → 空数组", () => {
    expect(normalizeBatches({ ok: true } as never)).toEqual([]);
  });
});
