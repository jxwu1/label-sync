import unittest
from unittest import mock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.services import attendance_report as rpt
from app.services import attendance as svc


class _DBTestCase(unittest.TestCase):
    def setUp(self):
        import app.models as models_mod

        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def _enable_fk(dbapi_conn, _):
            dbapi_conn.cursor().execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)
        self.patch_engine = mock.patch.object(models_mod, "_engine", self.engine)
        self.patch_session = mock.patch.object(models_mod, "_SessionFactory", self.Session)
        self.patch_engine.start()
        self.patch_session.start()

    def tearDown(self):
        self.patch_session.stop()
        self.patch_engine.stop()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()


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
