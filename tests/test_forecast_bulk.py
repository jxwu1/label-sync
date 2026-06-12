"""bulk 预取路径等价性测试 — refresh 查询风暴改造 (2026-06-12)。

三个 *_bulk 函数（weekly_demand_series_bulk / stockout_weeks_bulk /
build_routed_series_bulk）必须与单 SKU 版逐 SKU 完全一致 —— 这是 E5
（双实现漂移）的防线：bulk 路径任何语义分叉都在这里炸。

附查询次数断言：bulk 路径每批查询数为常数，不随 SKU 数增长。
seed 全走 SQLAlchemy（PG 腿要过）。
"""

from __future__ import annotations

import datetime as dt

from app.models import InventoryEvent, Stockpile, StockpileInventorySnapshot
from app.repositories import stockpile_db

_AS_OF = dt.date(2026, 6, 8)  # 周一，窗口末端
_WEEKS = 20


def _seed_sales(barcode: str, docs: list[tuple[int, int]], doc_prefix: str = "DOC") -> None:
    """docs: list of (weeks_ago, qty) — 每条一个独立 document_no。"""
    with stockpile_db._session() as s:
        for i, (weeks_ago, qty) in enumerate(docs):
            d = _AS_OF - dt.timedelta(days=7 * weeks_ago)
            s.add(
                InventoryEvent(
                    event_at=d.isoformat(),
                    event_type="sale",
                    product_barcode=barcode,
                    qty=qty,
                    document_no=f"{doc_prefix}-{barcode}-{i}",
                )
            )
        s.commit()


def _seed_return_pair(barcode: str, weeks_ago: int, qty: int) -> None:
    """同 doc 一正一负完全冲销（净量 0 → 整 doc 丢弃）。"""
    d = _AS_OF - dt.timedelta(days=7 * weeks_ago)
    with stockpile_db._session() as s:
        for q in (qty, -qty):
            s.add(
                InventoryEvent(
                    event_at=d.isoformat(),
                    event_type="sale",
                    product_barcode=barcode,
                    qty=q,
                    document_no=f"RET-{barcode}",
                )
            )
        s.commit()


def _seed_empty_doc_events(barcode: str, weeks_ago: int, qtys: list[int]) -> None:
    """空 document_no 事件 —— 必须按事件主键独立成 doc，不得并桶。"""
    d = _AS_OF - dt.timedelta(days=7 * weeks_ago)
    with stockpile_db._session() as s:
        for q in qtys:
            s.add(
                InventoryEvent(
                    event_at=d.isoformat(),
                    event_type="sale",
                    product_barcode=barcode,
                    qty=q,
                    document_no=None,
                )
            )
        s.commit()


def _seed_stockpile(barcode: str, model: str) -> None:
    with stockpile_db._session() as s:
        s.add(
            Stockpile(
                product_barcode=barcode,
                product_model=model,
                stockpile_location="A1",
                is_active=1,
            )
        )
        s.commit()


def _seed_snapshot(model: str, monday: dt.date, qty_total: int) -> None:
    with stockpile_db._session() as s:
        s.add(
            StockpileInventorySnapshot(
                snapshot_date=monday.isoformat(), product_model=model, qty_total=qty_total
            )
        )
        s.commit()


def _seed_world() -> list[str]:
    """五种形态 + 退货/空单号 + 缺货周，返回全部 barcode。"""
    # R1 零售主导：14 周每周一单小额（retail ratio 1.0，序列长度过 _MIN_FIT_WEEKS）
    _seed_sales("BULK-R1", [(w, 5) for w in range(1, 15)])
    # S1 零售 + 缺货周：同 R1，另有周一快照 qty_total=0（2 周前）
    _seed_sales("BULK-S1", [(w, 4) for w in range(1, 15)])
    _seed_stockpile("BULK-S1", "MS1")
    _seed_snapshot("MS1", _AS_OF - dt.timedelta(days=14), 0)
    _seed_snapshot("MS1", _AS_OF - dt.timedelta(days=28), 9)  # 有货周对照，不剔
    # W1 纯批发：8 个非零周大单（≥5 过准入闸）
    _seed_sales("BULK-W1", [(w, 100) for w in (1, 3, 5, 7, 9, 11, 13, 15)])
    # W2 批发但非零周不足：3 个 → 不预测
    _seed_sales("BULK-W2", [(w, 100) for w in (2, 6, 10)])
    # D1 深度死亡：最后销售 30 周前
    _seed_sales("BULK-D1", [(30, 50), (35, 60)])
    # RET 退货归并 + 空单号语义（分类为何不重要，weekly 等价才是测点）
    _seed_sales("BULK-RET", [(w, 6) for w in range(1, 15)])
    _seed_return_pair("BULK-RET", 2, 8)
    _seed_empty_doc_events("BULK-RET", 3, [2, 3])
    return ["BULK-R1", "BULK-S1", "BULK-W1", "BULK-W2", "BULK-D1", "BULK-RET", "BULK-GHOST"]


class TestBulkEquivalence:
    def test_weekly_demand_series_bulk_matches_single(self):
        bcs = _seed_world()
        from app.utils.forecast_data import weekly_demand_series, weekly_demand_series_bulk

        with stockpile_db._session() as s:
            bulk = weekly_demand_series_bulk(bcs, _AS_OF, _WEEKS, session=s)
            for bc in bcs:
                assert bulk[bc] == weekly_demand_series(bc, _AS_OF, _WEEKS, session=s), bc

    def test_stockout_weeks_bulk_matches_single(self):
        bcs = _seed_world()
        from app.services.stockout import stockout_weeks, stockout_weeks_bulk

        with stockpile_db._session() as s:
            bulk = stockout_weeks_bulk(bcs, _AS_OF, _WEEKS, session=s)
            for bc in bcs:
                assert bulk[bc] == stockout_weeks(bc, _AS_OF, _WEEKS, session=s), bc
        # 缺货周确实被识别（防测试空转）
        assert bulk["BULK-S1"] == {_AS_OF - dt.timedelta(days=14)}

    def test_build_routed_series_bulk_matches_single(self):
        bcs = _seed_world()
        from app.services.forecast import build_routed_series, build_routed_series_bulk

        with stockpile_db._session() as s:
            bulk = build_routed_series_bulk(bcs, _AS_OF, _WEEKS, session=s)
            for bc in bcs:
                assert bulk[bc] == build_routed_series(bc, _AS_OF, _WEEKS, session=s), bc
        # 路由结果非平凡（防测试空转）：R1 走 EmpQuant，W1 走 CrostonSBA，
        # W2/D1/GHOST 出局，S1 剔了 1 个缺货周
        assert bulk["BULK-R1"][3] == "EmpiricalQuantile"
        assert bulk["BULK-W1"][3] == "CrostonSBA"
        assert bulk["BULK-W2"] is None
        assert bulk["BULK-D1"] is None
        assert bulk["BULK-GHOST"] is None
        assert bulk["BULK-S1"][2] == 1

    def test_bulk_query_count_constant(self):
        """bulk 路径每批查询数为常数（≤8），不随 SKU 数增长。"""
        bcs = _seed_world()
        from sqlalchemy import event

        from app import db
        from app.services.forecast import build_routed_series_bulk

        engine = db.get_engine()
        counter = {"n": 0}

        def _count(conn, cursor, statement, parameters, context, executemany):
            counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _count)
        try:
            with stockpile_db._session() as s:
                build_routed_series_bulk(bcs, _AS_OF, _WEEKS, session=s)
        finally:
            event.remove(engine, "before_cursor_execute", _count)
        assert counter["n"] <= 8, f"bulk 路径查询数膨胀: {counter['n']}"


class TestRefreshUsesBulk:
    def test_refresh_output_unchanged_by_bulk_path(self):
        """refresh 走 bulk 后产出行与路由语义一致（端到端回归）。"""
        bcs = _seed_world()
        for bc in bcs:
            if bc not in ("BULK-S1",):  # S1 已有主档
                _seed_stockpile(bc, f"M{bc[-3:]}")
        from sqlalchemy import select

        from app.models import ForecastOutput
        from app.services.forecast import refresh_forecast_output

        result = refresh_forecast_output(end_date=_AS_OF, weeks=_WEEKS, barcodes=bcs)
        assert result["n_written"] == 4  # R1 + S1 + W1 + RET(退货SKU本身合格)
        with stockpile_db._session() as s:
            rows = {r.product_barcode: r for r in s.execute(select(ForecastOutput)).scalars().all()}
        assert set(rows) == {"BULK-R1", "BULK-S1", "BULK-W1", "BULK-RET"}
        assert rows["BULK-R1"].model_used == "EmpiricalQuantile"
        assert rows["BULK-W1"].model_used == "CrostonSBA"
        assert rows["BULK-S1"].stockout_weeks_excluded == 1
