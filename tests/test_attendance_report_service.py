import unittest

from app.services import attendance as svc
from app.services import attendance_report as rpt


class _DBTestCase(unittest.TestCase):
    # DB 隔离由 conftest autouse 提供（tmp sqlite，经 app.db engine）。
    pass


class TestBuildPayrollPdf(_DBTestCase):
    def test_returns_pdf_bytes(self):
        svc.create_employee("小王")
        data = rpt.build_payroll_pdf("2026-04")
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 100)

    def test_empty_month_still_works(self):
        data = rpt.build_payroll_pdf("2099-01")
        self.assertTrue(data.startswith(b"%PDF"))


class TestBuildPdf(_DBTestCase):
    def test_pdf_returns_non_empty_bytes(self):
        svc.create_employee("小王")
        svc.set_day("e001", "2026-04-01", {"start": "09:30", "end": "20:00"})
        data = rpt.build_pdf("2026-04")
        self.assertIsInstance(data, bytes)
        self.assertGreater(len(data), 100)
        self.assertTrue(data.startswith(b"%PDF"))

    def test_pdf_empty_month_still_works(self):
        data = rpt.build_pdf("2099-01")
        self.assertTrue(data.startswith(b"%PDF"))


class TestBundledCJKFont(unittest.TestCase):
    """回归：仓库必须自带可注册的 CJK 字体，否则 Linux 生产回退 Helvetica → 中文方块。

    Windows 本地有 C:/Windows/Fonts/*，会掩盖此 bug，所以直接断言第一候选
    (打包字体) 存在且能注册 + 含中文字形——跨平台有效。
    """

    def test_bundled_font_is_first_candidate(self):
        from app.config import CONFIG

        expected = CONFIG.resource_dir / "static" / "fonts" / "NotoSansSC-Regular.ttf"
        self.assertEqual(rpt._FONT_CANDIDATES[0], expected)

    def test_bundled_font_ships_and_registers_with_cjk_glyphs(self):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        font_path = rpt._FONT_CANDIDATES[0]
        self.assertTrue(
            font_path.exists(),
            f"打包 CJK 字体缺失：{font_path}（缺了它 Linux 生产 PDF 中文会变方块）",
        )
        pdfmetrics.registerFont(TTFont("_CjkRegressionCheck", str(font_path)))
        face = pdfmetrics.getFont("_CjkRegressionCheck").face
        for ch in "工资单考勤台账月度汇总":
            self.assertTrue(
                face.charToGlyph.get(ord(ch)),
                f"字体缺中文字形：{ch}",
            )
