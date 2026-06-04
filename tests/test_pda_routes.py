import unittest
from unittest import mock
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Employee
from app.routes.pda import bp


def _db():
    e = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(e, "connect")
    def _fk(c, _):
        c.cursor().execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(e)
    return e, sessionmaker(bind=e, future=True, expire_on_commit=False)


class PdaRouteTests(unittest.TestCase):
    def setUp(self):
        import app.models as m

        self.engine, self.Session = _db()
        self.pe = mock.patch.object(m, "_engine", self.engine)
        self.pe.start()
        self.ps = mock.patch.object(m, "_SessionFactory", self.Session)
        self.ps.start()
        s = self.Session()
        s.add(Employee(employee_id="e001", name="张三", active=1, is_scanner=1))
        s.commit()
        s.close()
        self.app = Flask(__name__)
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    def tearDown(self):
        self.ps.stop()
        self.pe.stop()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_operators_lists_only_scanners(self):
        rv = self.client.get("/pda/operators")
        self.assertEqual(rv.status_code, 200)
        names = [o["name"] for o in rv.get_json()["operators"]]
        self.assertEqual(names, ["张三"])

    def test_scan_flow(self):
        sid = self.client.post(
            "/pda/session/start", json={"operator_employee_id": "e001"}
        ).get_json()["session_id"]
        self.client.post(f"/pda/session/{sid}/scan", json={"raw": "C08-12-03"})
        body = self.client.post(
            f"/pda/session/{sid}/scan", json={"raw": "5828079343379"}
        ).get_json()
        self.assertEqual(body["item_count"], 2)
        und = self.client.post(f"/pda/session/{sid}/undo").get_json()
        self.assertEqual(und["item_count"], 1)
        fin = self.client.post(f"/pda/session/{sid}/finalize").get_json()
        self.assertEqual(fin["status"], "pending")

    def _start_with_loc(self):
        sid = self.client.post(
            "/pda/session/start", json={"operator_employee_id": "e001"}
        ).get_json()["session_id"]
        self.client.post(f"/pda/session/{sid}/scan", json={"raw": "C08-12-03"})
        self.client.post(f"/pda/session/{sid}/scan", json={"raw": "5828079343379"})
        return sid

    def test_update_item_endpoint(self):
        sid = self._start_with_loc()
        body = self.client.post(
            f"/pda/session/{sid}/update-item", json={"seq": 1, "raw": "D09-01-02"}
        ).get_json()
        self.assertEqual(body["rows"][0]["raw"], "D09-01-02")
        self.assertEqual(body["rows"][0]["kind"], "location")
        self.assertEqual(body["item_count"], 2)  # 覆盖不新增行

    def test_update_item_missing_seq_returns_400(self):
        sid = self._start_with_loc()
        rv = self.client.post(f"/pda/session/{sid}/update-item", json={"raw": "X-1"})
        self.assertEqual(rv.status_code, 400)

    def test_update_item_bad_seq_returns_400(self):
        sid = self._start_with_loc()
        rv = self.client.post(f"/pda/session/{sid}/update-item", json={"seq": 99, "raw": "X-1"})
        self.assertEqual(rv.status_code, 400)
