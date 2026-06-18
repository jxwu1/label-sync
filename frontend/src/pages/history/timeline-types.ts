export interface TimelineWeekVM {
  weekStart: string;
  saleQty: number;
  purchaseUnitPrice: number | null;
  rawUnitPriceLocal: number | null;
  currencyLocal: string;
}
export interface MonthlySaleVM {
  monthStart: string;
  saleQty: number;
  retailQty: number;
}
export interface TimelineVM {
  weeks: TimelineWeekVM[];
  monthlySales: MonthlySaleVM[];
}
