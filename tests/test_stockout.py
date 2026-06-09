"""stockout_weeks: 周一唯一口径 + qty_total<=0 缺货判定 (spec §6 ①-⑧)。

Pattern: no db_session fixture — use stockpile_db._session() directly (same
as test_analytics_service.py). autouse _isolate_db in conftest handles
per-test tmp sqlite isolation.
"""

from datetime import date

from sqlalchemy import insert

from app.models import Stockpile, StockpileInventorySnapshot
from app.repositories import stockpile_db
from app.services.stockout import stockout_weeks


def _seed_stockpile(barcode="BC1", model="M1"):
    with stockpile_db._session() as s:
        s.execute(
            insert(Stockpile).values(
                product_barcode=barcode,
                product_model=model,
                stockpile_location="A1",
            )
        )
        s.commit()


def _add_snap(model, snapshot_date, qty_total):
    with stockpile_db._session() as s:
        s.execute(
            insert(StockpileInventorySnapshot).values(
                snapshot_date=snapshot_date,
                product_model=model,
                qty_total=qty_total,
            )
        )
        s.commit()


# 三个连续周一 (ISO): 2026-05-25 / 2026-06-01 / 2026-06-08
_MON1, _MON2, _MON3 = "2026-05-25", "2026-06-01", "2026-06-08"
_END = date(2026, 6, 8)  # 含 6-08 的 ISO 周一 = 6-08


def test_monday_qty_zero_is_stockout():
    _seed_stockpile()
    _add_snap("M1", _MON3, 0)
    out = stockout_weeks("BC1", _END, weeks=3)
    assert date(2026, 6, 8) in out


def test_monday_qty_positive_not_stockout():
    _seed_stockpile()
    _add_snap("M1", _MON3, 5)
    out = stockout_weeks("BC1", _END, weeks=3)
    assert date(2026, 6, 8) not in out


def test_negative_qty_is_stockout():
    # 超卖待到货 qty_total<0 → 物理无货 → 缺货 (<=0 口径)
    _seed_stockpile()
    _add_snap("M1", _MON3, -3)
    out = stockout_weeks("BC1", _END, weeks=3)
    assert date(2026, 6, 8) in out


def test_week_without_monday_snapshot_is_unknown():
    # 只有更早一周的快照, 末周无周一快照 → 末周不判缺货
    _seed_stockpile()
    _add_snap("M1", _MON1, 0)
    out = stockout_weeks("BC1", _END, weeks=3)
    assert date(2026, 6, 8) not in out
    assert date(2026, 5, 25) in out


def test_same_week_monday_zero_wednesday_five_is_stockout():
    # 周一 0 周三 5: 只看周一 → 缺货 (周三那条 snapshot_date 不是周一, 被忽略)
    _seed_stockpile()
    _add_snap("M1", _MON3, 0)
    _add_snap("M1", "2026-06-10", 5)  # 周三
    out = stockout_weeks("BC1", _END, weeks=3)
    assert date(2026, 6, 8) in out


def test_same_week_monday_five_wednesday_zero_not_stockout():
    # 周一 5 周三 0: 只看周一 → 不缺货
    _seed_stockpile()
    _add_snap("M1", _MON3, 5)
    _add_snap("M1", "2026-06-10", 0)  # 周三售空, 忽略
    out = stockout_weeks("BC1", _END, weeks=3)
    assert date(2026, 6, 8) not in out


def test_multi_barcode_same_model_share_qty():
    # 两个 barcode 同 model, 快照 model 级 → 都按同一 qty_total 判
    _seed_stockpile(barcode="BC1", model="M9")
    _seed_stockpile(barcode="BC2", model="M9")
    _add_snap("M9", _MON3, 0)
    out1 = stockout_weeks("BC1", _END, weeks=3)
    out2 = stockout_weeks("BC2", _END, weeks=3)
    assert date(2026, 6, 8) in out1
    assert date(2026, 6, 8) in out2


def test_barcode_without_model_returns_empty():
    out = stockout_weeks("NO_SUCH_BC", _END, weeks=3)
    assert out == set()
