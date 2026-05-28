"""企业微信考勤导入：解析层 + 服务 + 计划层单测。"""
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Employee


def _make_memory_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        dbapi_conn.cursor().execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return engine, Session


class WecomAccountColumnTests(unittest.TestCase):
    def test_employee_has_wecom_account(self):
        engine, Session = _make_memory_db()
        with Session() as s:
            s.add(Employee(employee_id="e001", name="张三", wecom_account="ZhangSan"))
            s.commit()
        with Session() as s:
            emp = s.get(Employee, "e001")
            self.assertEqual(emp.wecom_account, "ZhangSan")
        engine.dispose()
