export interface RecentBatchVM {
  batchId: number;
  takenAt: string | null;
  totalLocal: number | null;
  changeCount: number;
  affectedBarcodes: number;
  isOpen: boolean;
}

export interface RecentSummaryVM {
  locationChanges: number;
  modelChanges: number;
  inserts: number;
  deactivates: number;
  reactivates: number;
  roundtripCount: number;
}

export interface ChangeRowVM {
  barcode: string;
  model: string;
  field: string;
  fromValue: string | null;
  toValue: string | null;
  changeType: string;
  at: string;
}

export interface RecentDetailVM {
  summary: RecentSummaryVM;
  changes: ChangeRowVM[];
  totalCount: number;
}
