export interface ScanXlsxFileVM {
  name: string;
  sizeBytes: number;
}

export interface ScanBatchVM {
  batchId: string;
  employee: string;
  scannedAt: string;
  csvFilename: string | null;
  csvRows: number | null;
  csvSizeBytes: number | null;
  xlsxFiles: ScanXlsxFileVM[];
}
