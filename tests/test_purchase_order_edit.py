"""采购单编辑契约: 改下单日期 + 作废软删 (用户 2026-06-05 需求).

update 只改 order_date, 数量单价不动; 到货是状态转换, 走 /arrival 不进 update。
作废=软删 status='void' 保留可查, 且排除出前置期统计。
缺单 → LookupError(→404); 坏日期 → ValueError(→400)。
"""

import pytest
from sqlalchemy import insert

from app.models import PurchaseOrder, Supplier, get_session
from app.services import purchase as svc


def _seed_order(**kw) -> int:
    vals = {
        "supplier_id": "S1",
        "order_date": "2026-05-01",
        "status": "placed",
        "total_qty": 10,
        "total_amount": 100.0,
    }
    vals.update(kw)
    with get_session() as s:
        res = s.execute(insert(PurchaseOrder).values(**vals))
        s.commit()
        return res.inserted_primary_key[0]


def _seed_supplier(supplier_id="S1", supplier_name="供应商一") -> None:
    with get_session() as s:
        if s.get(Supplier, supplier_id) is None:
            s.execute(insert(Supplier).values(supplier_id=supplier_id, supplier_name=supplier_name))
            s.commit()


def test_update_order_changes_order_date():
    oid = _seed_order()
    svc.update_order(oid, order_date="2026-05-15")
    with get_session() as s:
        assert s.get(PurchaseOrder, oid).order_date == "2026-05-15"


def test_update_order_leaves_arrival_and_status_untouched():
    """方向 A: update 只管 order_date; 到货是状态转换, 走 /arrival。

    改下单日期不该碰 arrival_date/status, 否则会造出"有到货日期但仍 placed"的脏单。
    """
    oid = _seed_order(order_date="2026-05-01", arrival_date=None, status="placed")
    svc.update_order(oid, order_date="2026-05-09")
    with get_session() as s:
        o = s.get(PurchaseOrder, oid)
        assert o.order_date == "2026-05-09"
        assert o.arrival_date is None
        assert o.status == "placed"


def test_update_order_rejects_arrival_date_kwarg():
    """到货日期不在 update 契约内: 传 arrival_date 直接 TypeError, 逼调用方走 /arrival。"""
    oid = _seed_order()
    with pytest.raises(TypeError):
        svc.update_order(oid, arrival_date="2026-05-10")


def test_update_order_rejects_bad_date():
    oid = _seed_order()
    with pytest.raises(ValueError):
        svc.update_order(oid, order_date="not-a-date")


def test_update_order_missing_raises_lookup():
    with pytest.raises(LookupError):
        svc.update_order(99999, order_date="2026-05-15")


def test_void_order_marks_status_void():
    oid = _seed_order()
    svc.void_order(oid)
    with get_session() as s:
        assert s.get(PurchaseOrder, oid).status == "void"


def test_void_order_missing_raises_lookup():
    with pytest.raises(LookupError):
        svc.void_order(99999)


def test_list_orders_still_returns_voided_with_status():
    oid = _seed_order()
    svc.void_order(oid)
    orders = svc.list_orders()
    row = next(x for x in orders if x["id"] == oid)
    assert row["status"] == "void"


def test_voided_order_excluded_from_lead_times():
    """作废单不得污染供应商前置期统计 (void 引入的下游副作用)。

    一张正常到货单(7 天) + 一张被作废的离谱长单(120 天):
    前置期只能算正常那张, 否则中位数被作废单拉飞。
    """
    _seed_supplier("S1", "供应商一")
    _seed_order(
        supplier_id="S1", order_date="2026-05-01", arrival_date="2026-05-08", status="arrived"
    )
    bad = _seed_order(supplier_id="S1", order_date="2026-05-01", arrival_date="2026-09-01")
    svc.void_order(bad)

    stats = svc.compute_supplier_lead_times()
    row = next(x for x in stats if x["supplier_id"] == "S1")
    assert row["n_samples"] == 1
    assert row["median_days"] == 7
