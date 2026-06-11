"""缺货周判定 (spec 2026-06-09 §5.1)。

第一期地基: 用周一库存快照判定某周是否缺货, 供置信度分层"有货零销 vs 缺货
零销"拆分, 以及第二期需求清洗复用。

判定口径 (经 review 收紧):
- 周键 = 各 ISO 周的周一 date。
- 周一唯一: 只看 snapshot_date == 该周周一 的快照, 不取周中/最接近的快照。
- 该周一快照 qty_total <= 0 → 缺货 (负库存=ERP 超卖待到货=物理无货, 同
  restock_calc.py:197 "<0 视为 0 库存" 口径)。
- 无周一快照 → unknown, 不判缺货 (保守)。
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Stockpile, StockpileInventorySnapshot
from app.repositories import stockpile_db
from app.utils.forecast_data import _monday


def stockout_weeks(
    barcode: str,
    end_date: date,
    weeks: int,
    session: Session | None = None,
) -> set[date]:
    """返回窗口内判定为缺货的周 (周一 date 集合)。

    窗口与 weekly_demand_series 对齐: 末周 = 含 end_date 的 ISO 周, 向前 weeks 周。
    """
    if weeks < 1:
        raise ValueError("weeks must be >= 1")
    end_monday = _monday(end_date)
    week_mondays = [end_monday - timedelta(days=7 * (weeks - 1 - i)) for i in range(weeks)]
    monday_strs = [w.isoformat() for w in week_mondays]

    def _q(s: Session) -> set[date]:
        model = s.execute(
            select(Stockpile.product_model).where(Stockpile.product_barcode == barcode)
        ).scalar_one_or_none()
        if model is None:
            return set()
        rows = s.execute(
            select(
                StockpileInventorySnapshot.snapshot_date,
                StockpileInventorySnapshot.qty_total,
            ).where(
                StockpileInventorySnapshot.product_model == model,
                StockpileInventorySnapshot.snapshot_date.in_(monday_strs),
            )
        ).all()
        return {date.fromisoformat(d) for d, qty in rows if qty <= 0}

    if session is not None:
        return _q(session)
    with stockpile_db._session() as s:
        return _q(s)


def exclude_stockout_weeks(
    series: dict[date, float],
    stockout: set[date],
) -> dict[date, float]:
    """缺货周从训练序列剔除（当缺失，不填 0 不插值）— RL-3 / ADR-0001 D7.

    缺货周的 0 销量是删失观测不是真实需求，入训练会拉低分位数 →
    补货更少 → 更缺货（死亡螺旋）。
    """
    return {wk: qty for wk, qty in series.items() if wk not in stockout}
