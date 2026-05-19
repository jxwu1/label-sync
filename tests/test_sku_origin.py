"""classify_origin 单测 (sku_origin §9.3 落地)."""

from __future__ import annotations

import unittest

from app.services.sku_origin import classify_origin


class ClassifyOriginTests(unittest.TestCase):
    def test_cn_supplier_prefix(self) -> None:
        assert classify_origin("CN001", "12345") == "CN"
        assert classify_origin("CN999X", "1234567890123") == "CN"

    def test_foreign_supplier_prefixes(self) -> None:
        for sid in ["GR12", "ES01", "TR9", "BG7", "NE3", "IT5"]:
            assert classify_origin(sid, "12345") == "FOREIGN"

    def test_supplier_overrides_model_heuristic(self) -> None:
        # 5 位 model 倾向 CN 启发式; 但 GR 供应商前缀强制 FOREIGN
        assert classify_origin("GR01", "12345") == "FOREIGN"
        # 13 位 model 倾向 FOREIGN; 但 CN 供应商前缀强制 CN
        assert classify_origin("CN01", "1234567890123") == "CN"

    def test_unknown_supplier_prefix_falls_back_to_model(self) -> None:
        assert classify_origin("US01", "12345") == "CN"
        assert classify_origin("US01", "1234567890123") == "FOREIGN"

    def test_model_len_5_no_supplier(self) -> None:
        assert classify_origin(None, "12345") == "CN"
        assert classify_origin("", "00000") == "CN"

    def test_model_len_13_no_supplier(self) -> None:
        assert classify_origin(None, "1234567890123") == "FOREIGN"

    def test_model_other_length_unknown(self) -> None:
        assert classify_origin(None, "ABC") == "unknown"
        assert classify_origin(None, "12345678") == "unknown"

    def test_both_missing_unknown(self) -> None:
        assert classify_origin(None, None) == "unknown"
        assert classify_origin("", "") == "unknown"

    def test_lowercase_supplier_prefix(self) -> None:
        assert classify_origin("cn123", "12345") == "CN"
        assert classify_origin("gr44", "12345") == "FOREIGN"


if __name__ == "__main__":
    unittest.main()
