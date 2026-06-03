"""sku_summary 物化表测试（货号历史/dashboard 提速方案）。

设计：新表 sku_summary = product_barcode(PK) + as_of(date) + payload(item dict 的 JSON)
+ computed_at。refresh 复用现有 _list_sku_summary_impl，读路径查表 + 空表/过期回退实时。
"""

from __future__ import annotations

import shutil
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from app.repositories import stockpile_db

TEST_TMP_DIR = Path(__file__).resolve().parent / "_test_sku_summary"


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = TEST_TMP_DIR / self._testMethodName
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db = self.test_dir / "test.db"
        self.patch = mock.patch.object(stockpile_db, "DB_PATH", self.test_db)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        stockpile_db._engine_cache.clear()
        stockpile_db.ensure_db()
        from app.services import analytics as _ans
        _ans.clear_list_sku_summary_cache()

    def tearDown(self) -> None:
        stockpile_db._engine_cache.clear()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _add_sku(self, barcode: str, **fields) -> None:
        from sqlalchemy import insert

        from app.models import Stockpile

        values = {
            "product_barcode": barcode,
            "product_model": barcode,
            "stockpile_location": "",
            "is_active": 1,
        }
        values.update(fields)
        with stockpile_db._session() as s:
            s.execute(insert(Stockpile).values(**values))
            s.commit()

    def _add_event(
        self,
        *,
        barcode: str = "B1",
        event_type: str = "sale",
        event_at: str,
        qty: int,
        unit_price: float | None = None,
        document_no: str | None = None,
        supplier_id: str | None = None,
    ) -> None:
        from sqlalchemy import insert

        from app.models import InventoryEvent

        with stockpile_db._session() as s:
            s.execute(
                insert(InventoryEvent).values(
                    event_at=event_at,
                    event_type=event_type,
                    product_barcode=barcode,
                    qty=qty,
                    unit_price=unit_price,
                    document_no=document_no,
                    supplier_id=supplier_id,
                )
            )
            s.commit()

    def _insert_summary(self, barcode: str, as_of: str, payload: dict) -> None:
        from sqlalchemy import insert

        from app.models import SkuSummary

        with stockpile_db._session() as s:
            s.execute(
                insert(SkuSummary).values(
                    product_barcode=barcode, as_of=as_of, payload=payload
                )
            )
            s.commit()


class TestSkuSummaryModel(_Base):
    def test_row_round_trips_with_json_payload(self) -> None:
        """SkuSummary 行可写入并读回，payload 保持原 dict 结构。"""
        from sqlalchemy import insert, select

        from app.models import SkuSummary

        payload = {"product_barcode": "B1", "qty_30d": 12, "nested": {"a": [1, 2]}}
        with stockpile_db._session() as s:
            s.execute(
                insert(SkuSummary).values(
                    product_barcode="B1",
                    as_of=date(2026, 6, 3).isoformat(),
                    payload=payload,
                )
            )
        with stockpile_db._session() as s:
            row = s.execute(
                select(SkuSummary).where(SkuSummary.product_barcode == "B1")
            ).scalar_one()
        self.assertEqual(row.product_barcode, "B1")
        self.assertEqual(row.as_of, "2026-06-03")
        self.assertEqual(row.payload, payload)
        self.assertIsNotNone(row.computed_at)


class TestRefreshSkuSummary(_Base):
    def test_refresh_materializes_one_row_per_sku_matching_realtime(self) -> None:
        """refresh 后每个 active SKU 一行，payload 与实时计算逐字段一致（金标准对拍）。"""
        from sqlalchemy import select

        from app.models import SkuSummary
        from app.services.analytics import (
            _list_sku_summary_impl,
            refresh_sku_summary,
        )

        self._add_sku("S1", supplier_id="GR0001", sale_price=2.0,
                      last_purchase_unit_price=1.0)
        self._add_event(barcode="S1", event_at="2026-05-10", qty=5,
                        unit_price=2.0, document_no="W1")
        self._add_sku("S2", supplier_id="GR0001", sale_price=3.0)
        self._add_event(barcode="S2", event_at="2026-05-12", qty=2,
                        unit_price=3.0, document_no="W2")

        as_of = date(2026, 5, 21)
        golden = {it["barcode"]: it for it in _list_sku_summary_impl(as_of=as_of)}
        self.assertEqual(set(golden), {"S1", "S2"})  # 确认种子有效

        n = refresh_sku_summary(as_of=as_of)

        with stockpile_db._session() as s:
            rows = s.execute(select(SkuSummary)).scalars().all()
        self.assertEqual(n, len(golden))
        self.assertEqual({r.product_barcode for r in rows}, set(golden))
        for r in rows:
            self.assertEqual(r.as_of, as_of.isoformat())
            self.assertEqual(r.payload, golden[r.product_barcode])

    def test_refresh_invalidates_in_memory_list_cache(self) -> None:
        """refresh 重建表后清掉 list_sku_summary 的 60s 内存缓存，
        否则读路径会在 ≤60s 内继续吐旧列表。"""
        from app.services import analytics

        analytics._LIST_CACHE["key"] = (None,)
        analytics._LIST_CACHE["value"] = [{"barcode": "STALE"}]
        analytics._LIST_CACHE["ts"] = 9e9  # 远未过期

        analytics.refresh_sku_summary(as_of=date(2026, 5, 21))

        self.assertIsNone(analytics._LIST_CACHE["value"])

    def test_refresh_is_idempotent_overwrites_not_duplicates(self) -> None:
        """重复 refresh 整表重写，不累积重复行。"""
        from sqlalchemy import func, select

        from app.models import SkuSummary
        from app.services.analytics import refresh_sku_summary

        self._add_sku("S1", supplier_id="GR0001", sale_price=2.0)
        self._add_event(barcode="S1", event_at="2026-05-10", qty=5,
                        unit_price=2.0, document_no="W1")

        as_of = date(2026, 5, 21)
        refresh_sku_summary(as_of=as_of)
        refresh_sku_summary(as_of=as_of)

        with stockpile_db._session() as s:
            count = s.execute(select(func.count()).select_from(SkuSummary)).scalar_one()
        self.assertEqual(count, 1)


class TestListSkuSummaryReadsTable(_Base):
    def test_reads_payload_from_table_without_recompute(self) -> None:
        """表已物化 → 直接返回 payload，不重算（哨兵: 无任何 stockpile/event 种子，
        实时计算只会得空列表，得到哨兵即证明读了表）。"""
        from app.services.analytics import list_sku_summary

        as_of = date(2026, 5, 21)
        sentinel = {"barcode": "S1", "sentinel": True, "qty_30d": 999}
        self._insert_summary("S1", as_of.isoformat(), sentinel)

        result = list_sku_summary(as_of=as_of)
        self.assertEqual(result, [sentinel])

    def test_falls_back_to_realtime_when_table_empty(self) -> None:
        """空表 → 回退实时计算。"""
        from app.services.analytics import list_sku_summary

        self._add_sku("S1", supplier_id="GR0001", sale_price=2.0)
        self._add_event(barcode="S1", event_at="2026-05-10", qty=5,
                        unit_price=2.0, document_no="W1")
        result = list_sku_summary(as_of=date(2026, 5, 21))
        self.assertTrue(any(it["barcode"] == "S1" for it in result))

    def test_falls_back_when_table_as_of_stale(self) -> None:
        """表里只有旧 as_of 的行 → 视为过期，回退实时，不返回旧行。"""
        from app.services.analytics import list_sku_summary

        self._insert_summary("OLD", "2026-01-01", {"barcode": "OLD", "sentinel": True})
        self._add_sku("S1", supplier_id="GR0001", sale_price=2.0)
        self._add_event(barcode="S1", event_at="2026-05-10", qty=5,
                        unit_price=2.0, document_no="W1")
        result = list_sku_summary(as_of=date(2026, 5, 21))
        barcodes = {it["barcode"] for it in result}
        self.assertIn("S1", barcodes)
        self.assertNotIn("OLD", barcodes)


class TestReadSkuSummaryRow(_Base):
    def test_returns_single_payload_for_existing_barcode(self) -> None:
        from app.services.analytics import _read_sku_summary_row

        as_of = date(2026, 5, 21)
        payload = {"barcode": "S1", "urgency_score": 42}
        self._insert_summary("S1", as_of.isoformat(), payload)
        self.assertEqual(_read_sku_summary_row("S1", as_of), payload)

    def test_returns_none_when_barcode_absent(self) -> None:
        from app.services.analytics import _read_sku_summary_row

        self.assertIsNone(_read_sku_summary_row("NOPE", date(2026, 5, 21)))

    def test_returns_none_when_as_of_stale(self) -> None:
        from app.services.analytics import _read_sku_summary_row

        self._insert_summary("S1", "2026-01-01", {"barcode": "S1"})
        self.assertIsNone(_read_sku_summary_row("S1", date(2026, 5, 21)))


class TestRestockSnapshotUsesTable(_Base):
    def test_snapshot_avoids_full_recompute_when_row_materialized(self) -> None:
        """物化表有当日该货号行 → 不触发整表重算 (503 防护的关键不变量)。"""
        from app.services import analytics
        from app.services.analytics import _today, compute_restock_snapshot

        payload = {"barcode": "S1", "urgency_score": 7}
        self._insert_summary("S1", _today().isoformat(), payload)
        with mock.patch.object(
            analytics, "_list_sku_summary_impl",
            side_effect=AssertionError("compute_restock_snapshot 不应整表重算"),
        ):
            result = compute_restock_snapshot("S1")
        self.assertEqual(result, payload)

    def test_snapshot_returns_none_for_unknown_barcode(self) -> None:
        from app.services.analytics import compute_restock_snapshot

        self.assertIsNone(compute_restock_snapshot("NOPE"))


class TestPrewarmSkuSummary(_Base):
    def test_prewarm_populates_empty_table(self) -> None:
        """启动预热: 表空 → 重建落表 (否则单行快路径一直 miss)。"""
        from sqlalchemy import func, select

        from app.models import SkuSummary
        from app.services.analytics import prewarm_sku_summary

        self._add_sku("S1", supplier_id="GR0001", sale_price=2.0)
        prewarm_sku_summary()
        with stockpile_db._session() as s:
            n = s.execute(select(func.count()).select_from(SkuSummary)).scalar_one()
        self.assertEqual(n, 1)

    def test_prewarm_skips_refresh_when_table_fresh(self) -> None:
        """表已有当日数据 → 不重算 (哨兵: 无种子时真 refresh 会清空哨兵行)。"""
        from sqlalchemy import select

        from app.models import SkuSummary
        from app.services.analytics import _today, prewarm_sku_summary

        self._insert_summary("KEEP", _today().isoformat(), {"barcode": "KEEP"})
        prewarm_sku_summary()
        with stockpile_db._session() as s:
            rows = s.execute(select(SkuSummary.product_barcode)).scalars().all()
        self.assertEqual(rows, ["KEEP"])


if __name__ == "__main__":
    unittest.main()
