"""模型选择路由测试 — ADR-0002 D1 路由表逐行验收。

seed 全走 SQLAlchemy（PG 腿要过）。日期相对 _AS_OF 构造，保证分类稳定。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.models import ForecastOutput, InventoryEvent, Stockpile
from app.repositories import stockpile_db

_AS_OF = dt.date(2026, 6, 8)  # 周一，做窗口末端


def _seed_sales(barcode: str, docs: list[tuple[int, int]]) -> None:
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
                    document_no=f"DOC-{barcode}-{i}",
                )
            )
        s.commit()


def _seed_stockpile(barcode: str) -> None:
    with stockpile_db._session() as s:
        s.add(
            Stockpile(
                product_barcode=barcode,
                product_model=f"M{barcode[-4:]}",
                stockpile_location="A1",
                is_active=1,
            )
        )
        s.commit()


# ── build_routed_series 路由表逐行 ──────────────────────────────────────


class TestBuildRoutedSeries:
    def test_wholesale_routes_to_croston(self):
        """6 笔大单(qty 100, 零售样本 0 < 5) → wholesale_only → CrostonSBA。"""
        from app.services.forecast import build_routed_series

        bc = "7700000000001"
        _seed_sales(bc, [(1, 100), (3, 100), (5, 100), (7, 100), (9, 100), (11, 100)])
        with stockpile_db._session() as s:
            built = build_routed_series(bc, _AS_OF, weeks=13, session=s)
        assert built is not None
        series, sku_type, n_excluded, model_name, raw = built
        assert sku_type == "wholesale_only"
        assert model_name == "CrostonSBA"
        assert len(series) == 13  # 原始窗口周数(无缺货剔除)
        assert sum(1 for q in series if q > 0) == 6
        assert n_excluded == 0
        assert isinstance(raw, dict) and len(raw) == 13

    def test_wholesale_below_nonzero_gate_skipped(self):
        """非零周 < 5 的 wholesale → None（CrostonSBA interval 估计是噪声）。"""
        from app.services.forecast import build_routed_series

        bc = "7700000000002"
        _seed_sales(bc, [(1, 100), (4, 100), (8, 100)])  # 仅 3 个非零周
        with stockpile_db._session() as s:
            assert build_routed_series(bc, _AS_OF, weeks=13, session=s) is None

    def test_retail_routes_to_empirical_quantile(self):
        """30 笔小单(qty 2) → retail_dominant → EmpiricalQuantile（既有行为保持）。"""
        from app.services.forecast import build_routed_series

        bc = "7700000000003"
        _seed_sales(bc, [(w % 12, 2) for w in range(30)])
        with stockpile_db._session() as s:
            built = build_routed_series(bc, _AS_OF, weeks=13, session=s)
        assert built is not None
        _series, sku_type, _n_excl, model_name, _raw = built
        assert sku_type == "retail_dominant"
        assert model_name == "EmpiricalQuantile"

    def test_dying_not_forecast(self):
        """最后销售 20 周前 → dying → None（回测: 强预测 bias +0.89）。"""
        from app.services.forecast import build_routed_series

        bc = "7700000000004"
        _seed_sales(bc, [(20, 100), (22, 100), (24, 100), (26, 100), (28, 100)])
        with stockpile_db._session() as s:
            assert build_routed_series(bc, _AS_OF, weeks=30, session=s) is None

    def test_no_sales_unclassified_none(self):
        from app.services.forecast import build_routed_series

        with stockpile_db._session() as s:
            assert build_routed_series("7700000000005", _AS_OF, weeks=13, session=s) is None


# ── refresh 端到端: wholesale 行落库 ───────────────────────────────────


class TestRefreshWithRouting:
    def test_refresh_writes_croston_row_for_wholesale(self):
        from app.services.forecast import refresh_forecast_output

        bc = "7700000000010"
        _seed_stockpile(bc)
        _seed_sales(bc, [(1, 80), (3, 120), (5, 90), (7, 100), (9, 110), (11, 95)])

        refresh_forecast_output(end_date=_AS_OF, weeks=13, barcodes=[bc])

        with stockpile_db._session() as s:
            row = s.execute(
                select(ForecastOutput).where(ForecastOutput.product_barcode == bc)
            ).scalar_one()
        assert row.model_used == "CrostonSBA"
        assert row.sku_type == "wholesale_only"
        # horizon 列模型无关, bootstrap 照写 (ADR-0002 D3)
        assert row.p98_h is not None and row.p98_h > 0
        assert row.p50_h is not None
        assert row.horizon_weeks >= 2
        # 周字段非负 + 单调 (RL-5 口径)
        assert 0 <= row.p50 <= row.p98

    def test_refresh_still_writes_empirical_for_retail(self):
        from app.services.forecast import refresh_forecast_output

        bc = "7700000000011"
        _seed_stockpile(bc)
        _seed_sales(bc, [(w % 12, 2) for w in range(30)])

        refresh_forecast_output(end_date=_AS_OF, weeks=13, barcodes=[bc])

        with stockpile_db._session() as s:
            row = s.execute(
                select(ForecastOutput).where(ForecastOutput.product_barcode == bc)
            ).scalar_one()
        assert row.model_used == "EmpiricalQuantile"
        assert row.sku_type == "retail_dominant"
