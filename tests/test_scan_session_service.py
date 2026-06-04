import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app.services.scan_session as svc
from app.models import Employee, get_session


class ScanServiceTests(unittest.TestCase):
    def setUp(self):
        # DB 隔离由 conftest autouse 提供；这里 seed 员工 + patch INPUT_DIR（非 DB）。
        self._tmp = tempfile.mkdtemp()
        self.pin = mock.patch.object(svc, "INPUT_DIR", Path(self._tmp))
        self.pin.start()
        with get_session() as s:
            s.add(Employee(employee_id="e001", name="张三", active=1, is_scanner=1))
            s.add(Employee(employee_id="e002", name="李四", active=1, is_scanner=0))

    def tearDown(self):
        self.pin.stop()

    def test_start_requires_is_scanner(self):
        with self.assertRaises(ValueError):
            svc.start_session("e002")  # 非扫描员
        out = svc.start_session("e001")
        self.assertIn("session_id", out)

    def test_finalize_empty_rejected(self):
        sid = svc.start_session("e001")["session_id"]
        with self.assertRaises(ValueError):
            svc.finalize(sid)

    def test_materialize_parses_back_via_phase1(self):
        sid = svc.start_session("e001")["session_id"]
        for raw in ["C08-12-03", "5828079343379", "5828079343386", "C08-12-02", "5828079394951"]:
            svc.add_scan(sid, raw)
        path = svc.materialize_xlsx(sid)
        self.assertTrue(path.exists())
        self.assertEqual(path.stem, "张三")  # employee_name 来自文件名 stem

        # 用 phase1 的真实解析函数做回归
        from phase_scripts.update_location_phase1 import collect_location_map

        location_map = collect_location_map([path])
        self.assertEqual(
            location_map,
            {
                "5828079343379": ["C08-12-03"],
                "5828079343386": ["C08-12-03"],
                "5828079394951": ["C08-12-02"],
            },
        )

    def test_update_item_fixes_location_and_regroups_barcodes(self):
        sid = svc.start_session("e001")["session_id"]
        for raw in ["C08-12-03", "5828079343379", "5828079343386"]:
            svc.add_scan(sid, raw)
        # 第 1 行库位扫错 → 改成正确库位，条码不动
        out = svc.update_item(sid, 1, "C08-12-99")
        self.assertEqual(out["rows"][0]["raw"], "C08-12-99")
        self.assertEqual(out["rows"][0]["kind"], "location")
        self.assertEqual(out["item_count"], 3)  # 不新增行
        # phase1 重新解析 → 两个条码归到改后的库位
        path = svc.materialize_xlsx(sid)
        from phase_scripts.update_location_phase1 import collect_location_map

        self.assertEqual(
            collect_location_map([path]),
            {
                "5828079343379": ["C08-12-99"],
                "5828079343386": ["C08-12-99"],
            },
        )

    def test_update_item_empty_raw_rejected(self):
        sid = svc.start_session("e001")["session_id"]
        svc.add_scan(sid, "C08-12-03")
        with self.assertRaises(ValueError):
            svc.update_item(sid, 1, "   ")

    def test_update_item_bad_seq_rejected(self):
        sid = svc.start_session("e001")["session_id"]
        svc.add_scan(sid, "C08-12-03")
        with self.assertRaises(ValueError):
            svc.update_item(sid, 99, "X-1")

    def test_update_item_non_active_rejected(self):
        sid = svc.start_session("e001")["session_id"]
        svc.add_scan(sid, "C08-12-03")
        svc.finalize(sid)  # → pending，已交单不能再改
        with self.assertRaises(ValueError):
            svc.update_item(sid, 1, "X-1")
