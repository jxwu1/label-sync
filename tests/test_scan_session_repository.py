import unittest
from unittest import mock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Employee
import app.repositories.scan_session as repo


def _make_test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        dbapi_conn.cursor().execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, future=True, expire_on_commit=False)


class ScanRepoTests(unittest.TestCase):
    def setUp(self):
        import app.models as m
        self.engine, self.Session = _make_test_db()
        self.pe = mock.patch.object(m, "_engine", self.engine); self.pe.start()
        self.ps = mock.patch.object(m, "_SessionFactory", self.Session); self.ps.start()
        s = self.Session()
        s.add(Employee(employee_id="e001", name="张三", active=1)); s.commit(); s.close()

    def tearDown(self):
        self.ps.stop(); self.pe.stop()
        Base.metadata.drop_all(self.engine); self.engine.dispose()

    def test_create_and_append_assigns_seq_and_kind(self):
        sid = repo.create_session("e001", "张三")
        repo.append_item(sid, "C08-12-03")
        repo.append_item(sid, "5828079343379")
        items = repo.list_items(sid)
        self.assertEqual([i.seq for i in items], [1, 2])
        self.assertEqual([i.kind for i in items], ["location", "barcode"])
        self.assertEqual(repo.get_session_row(sid).item_count, 2)

    def test_pop_last_removes_highest_seq(self):
        sid = repo.create_session("e001", "张三")
        repo.append_item(sid, "C08-12-03")
        repo.append_item(sid, "5828079343379")
        self.assertTrue(repo.pop_last_item(sid))
        items = repo.list_items(sid)
        self.assertEqual([i.raw for i in items], ["C08-12-03"])
        self.assertEqual(repo.get_session_row(sid).item_count, 1)

    def test_active_and_pending(self):
        sid = repo.create_session("e001", "张三")
        self.assertEqual(repo.get_active_session().id, sid)
        repo.set_status(sid, "pending")
        self.assertIsNone(repo.get_active_session())
        self.assertEqual([s.id for s in repo.list_pending()], [sid])

    def test_update_item_by_seq_changes_value_keeps_others(self):
        sid = repo.create_session("e001", "张三")
        repo.append_item(sid, "C08-12-03")      # seq 1, location（扫错的库位）
        repo.append_item(sid, "5828079343379")  # seq 2, barcode
        repo.append_item(sid, "5828079343386")  # seq 3, barcode
        self.assertTrue(repo.update_item_by_seq(sid, 1, "D09-01-02"))
        items = repo.list_items(sid)
        self.assertEqual([i.raw for i in items], ["D09-01-02", "5828079343379", "5828079343386"])
        self.assertEqual([i.kind for i in items], ["location", "barcode", "barcode"])
        self.assertEqual(repo.get_session_row(sid).item_count, 3)  # 不新增/删除行

    def test_update_item_rederives_kind_on_overwrite(self):
        sid = repo.create_session("e001", "张三")
        repo.append_item(sid, "C08-12-03")  # location
        # 覆盖成纯数字 → kind 翻成 barcode（和重新扫一次同一规则）
        self.assertTrue(repo.update_item_by_seq(sid, 1, "5828079343379"))
        self.assertEqual(repo.list_items(sid)[0].kind, "barcode")

    def test_update_item_missing_seq_returns_false(self):
        sid = repo.create_session("e001", "张三")
        repo.append_item(sid, "C08-12-03")
        self.assertFalse(repo.update_item_by_seq(sid, 99, "X-1"))
