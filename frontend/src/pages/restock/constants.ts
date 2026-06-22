export interface FilterState {
  origin: string;
  views: { active: boolean; new: boolean; disc: boolean };
  band: string;
  coverMax: number | null;
  coverThreshold: number;
  supplier: string | null;
  show_ordered: boolean;
  search: string;
}

export const INITIAL_FILTER: FilterState = {
  origin: "FOREIGN",
  views: { active: true, new: false, disc: false },
  band: "all",
  coverMax: 4,
  coverThreshold: 4,
  supplier: null,
  show_ordered: false,
  search: "",
};

// 旧页「重置」非恢复初始默认：origin="" / coverMax=null（spec §6）
export const RESET_FILTER: FilterState = {
  origin: "",
  views: { active: true, new: false, disc: false },
  band: "all",
  coverMax: null,
  coverThreshold: 4,
  supplier: null,
  show_ordered: false,
  search: "",
};

export const THRESH = {
  HOT_URGENCY: 70,
  OVERSTOCK_WEEKS: 20,
  COVER_CAP: 13.0,
  SUPPLIER_OVERVIEW_HOT: 70,
  SUPPLIER_OVERVIEW_TOP: 5,
  ORDERED_EXPIRY_DAYS: 30,
} as const;

export const VISIBLE_CAP = 500;
export const INITIAL_SORT = { key: "urgency_score", dir: "desc" } as const;
