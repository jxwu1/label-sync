"""LK-1 回归测试: 分类与 IQR 清洗的 as_of 时间上界 (审计 2026-06-12 #1).

回测在历史时点调 classify_sku_type(as_of=end_date) / base_demand_view(end_date=...) 时,
cutoff 之后才出现的事件 (大单 / 销售) 绝不能反向改写该时点的分类与 IQR 阈值,
否则就是 look-ahead 泄漏。cutoff = 含 as_of 的 ISO 周的下一个周一 (exclusive),
与 weekly_demand_series.window_end_exclusive 同源。

生产 as_of=today 时未来事件不存在, 行为不变 (现有 test_categorizer 全绿守护)。
"""

from __future__ import annotations

import unittest
from datetime import date

from sqlalchemy import insert

from app.models import InventoryEvent
from app.repositories import stockpile_db


class _Base(unittest.TestCase):
    # DB 隔离由 conftest autouse _isolate_db 负责。

    def _add_sale(
        self,
        event_at: str,
        qty: int,
        barcode: str,
        document_no: str,
    ) -> None:
        with stockpile_db._session() as s:
            s.execute(
                insert(InventoryEvent).values(
                    event_at=event_at,
                    event_type="sale",
                    product_barcode=barcode,
                    qty=qty,
                    document_no=document_no,
                )
            )
            s.commit()


class ClassifyTypeAsofTests(_Base):
    def test_future_wholesale_does_not_rewrite_type(self) -> None:
        """cutoff 之前是 retail_dominant; cutoff 之后灌一堆大单。
        as_of 在过去 → 仍 retail_dominant; as_of=今天 → 被未来大单改写成 wholesale_only。
        证明上界确实挡住了未来。"""
        from app.utils.categorizer import classify_sku_type

        bc = "AF_TYPE"
        # 过去: 6 笔小零售单 (qty<=24) → retail_dominant
        for i in range(6):
            self._add_sale(f"2026-02-0{i + 1}", 5, bc, f"R{i}")
        # 未来 (cutoff 之后): 20 笔大批发单
        for i in range(20):
            self._add_sale("2026-05-10", 720, bc, f"W{i}")

        as_of_past = date(2026, 2, 28)
        assert classify_sku_type(bc, as_of=as_of_past) == "retail_dominant"

        # 对照: 把 as_of 推到未来事件之后, 大单应起作用 (6 零售 + 20 大单 →
        # 零售占比 6/26≈0.23, ∈[0.05,0.80) → mixed, 不再 retail_dominant)
        as_of_future = date(2026, 5, 13)
        assert classify_sku_type(bc, as_of=as_of_future) == "mixed"

    def test_dying_not_revived_by_future_sale(self) -> None:
        """as_of 在过去时, 之后才复活的 SKU 不能被未来销售救活 (审计 LK-1 路径 3)."""
        from app.utils.categorizer import classify_sku_type

        bc = "AF_DYING"
        # 最后一笔在过去 (距 as_of 远 >= 26 周深度死亡)
        self._add_sale("2025-08-01", 10, bc, "OLD")
        # 未来复活销售 (cutoff 之后)
        self._add_sale("2026-06-10", 10, bc, "NEW")

        as_of_past = date(2026, 5, 1)  # 距 2025-08-01 约 39 周 → dying
        assert classify_sku_type(bc, as_of=as_of_past) == "dying"

        # 对照: as_of 推到复活之后, 不再 dying
        as_of_future = date(2026, 6, 12)
        assert classify_sku_type(bc, as_of=as_of_future) != "dying"


class IqrThresholdAsofTests(_Base):
    def test_future_bulk_not_in_iqr_threshold(self) -> None:
        """base_demand_view 的 IQR 大单阈值不含 cutoff 之后的 doc:
        窗口内一笔中等单, 在"无未来大单"的阈值下应被当噪声剔除;
        若未来大单进了 IQR 分布, 阈值被抬高, 该单反而保留 → 用剔除计数区分两种口径。"""
        from app.utils.forecast_data import base_demand_view

        bc = "AF_IQR"
        # 历史小单群 (建立 median+IQR 的基线, qty 小且密集 → 阈值低)
        for i in range(12):
            self._add_sale(f"2026-04-{(i % 28) + 1:02d}", 4, bc, f"H{i}")
        # 窗口内一笔中等单 (相对历史阈值算大单, 应被剔)
        self._add_sale("2026-05-05", 60, bc, "MID")
        # 未来超大单 (cutoff 之后): 若被计入 IQR, 阈值飙高, MID 单不再算大单
        for i in range(8):
            self._add_sale("2026-06-10", 5000, bc, f"FUT{i}")

        end = date(2026, 5, 11)
        v = base_demand_view(bc, end_date=end, weeks=4)
        # retail_dominant (历史小单为主), 阈值不含未来 → MID(60) 被剔
        assert v["sku_type"] == "retail_dominant"
        assert v["exclusion_count"] >= 1, "未来超大单泄漏进了 IQR 阈值, MID 单未被剔除"


class BulkMatchesSingleAsofTests(_Base):
    def test_bulk_matches_single_with_future_events(self) -> None:
        """bulk 与单 SKU 路径在"有未来事件"时仍逐 SKU 等价 (反例 E5: 三处实现同步)."""
        from app.utils.forecast_data import base_demand_view, base_demand_views_bulk

        bc = "AF_BULK"
        for i in range(10):
            self._add_sale(f"2026-04-{(i % 28) + 1:02d}", 5, bc, f"H{i}")
        self._add_sale("2026-05-05", 80, bc, "MID")
        for i in range(6):
            self._add_sale("2026-06-10", 9000, bc, f"FUT{i}")

        end = date(2026, 5, 11)
        bulk = base_demand_views_bulk([bc], end_date=end, weeks=4)
        assert bulk[bc] == base_demand_view(bc, end_date=end, weeks=4)


if __name__ == "__main__":
    unittest.main()
