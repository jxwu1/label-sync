"""location_parser.parse_to_locations 单测。

子表 stockpile_locations 有 UNIQUE(stockpile_id, location)，
解析器必须对同 location 段去重，否则 import 会撞约束 → 500。
"""

import unittest

from app.parsers.location import parse_to_locations


class ParseToLocationsTests(unittest.TestCase):
    def test_empty_returns_empty_list(self) -> None:
        self.assertEqual(parse_to_locations(""), [])
        self.assertEqual(parse_to_locations(None), [])

    def test_single_segment(self) -> None:
        self.assertEqual(
            parse_to_locations("A22-04-04"),
            [{"location": "A22-04-04", "kind": "store", "position": 0}],
        )

    def test_multi_segment_keeps_order(self) -> None:
        result = parse_to_locations("A22-04-04/XB07-12")
        self.assertEqual([r["location"] for r in result], ["A22-04-04", "XB07-12"])
        self.assertEqual([r["position"] for r in result], [0, 1])
        self.assertEqual([r["kind"] for r in result], ["store", "warehouse"])

    def test_duplicate_segment_deduped_keep_first(self) -> None:
        """B06-20-02/XB07-12/XB07-12 → 只保留第一个 XB07-12，position 连续。"""
        result = parse_to_locations("B06-20-02/XB07-12/XB07-12")
        self.assertEqual(len(result), 2)
        self.assertEqual([r["location"] for r in result], ["B06-20-02", "XB07-12"])
        self.assertEqual([r["position"] for r in result], [0, 1])

    def test_duplicate_segment_only(self) -> None:
        result = parse_to_locations("XA09-04/XA09-04")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["location"], "XA09-04")
        self.assertEqual(result[0]["position"], 0)

    def test_whitespace_then_duplicate(self) -> None:
        """段间空格 strip 后变同 location 也应去重。"""
        result = parse_to_locations("XA09-04/ XA09-04 ")
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
