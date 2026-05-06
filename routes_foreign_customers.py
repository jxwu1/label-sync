"""老外客人月度记录 HTTP 路由。

端点：
- GET    /foreign-customers/customers          列出可选客户（含 type 排序）
- GET    /foreign-customers/records?month=&customer_id=  筛选记录
- POST   /foreign-customers/records            新建月度记录
- PUT    /foreign-customers/records/<id>       更新记录
- DELETE /foreign-customers/records/<id>       删除
- GET    /foreign-customers/summary/<month>    月度汇总
"""

from flask import Blueprint, jsonify
from pydantic import BaseModel

import foreign_customer_service
from route_helpers import NonEmptyStr, OptionalStr, parse_body

bp = Blueprint("foreign_customers", __name__, url_prefix="/foreign-customers")


class _RecordCreate(BaseModel):
    customer_id: NonEmptyStr
    record_month: NonEmptyStr  # 'YYYY-MM'
    amount_due: float | None = None
    tax_number: OptionalStr = ""
    payment_date: OptionalStr = ""
    shipping_date: OptionalStr = ""
    notes: OptionalStr = ""


class _RecordUpdate(BaseModel):
    amount_due: float | None = None
    tax_number: OptionalStr = ""
    payment_date: OptionalStr = ""
    shipping_date: OptionalStr = ""
    notes: OptionalStr = ""


def _normalize_optional(v: str | None) -> str | None:
    """空串 → None，让 DB 存 NULL 而不是空字符串。"""
    if v is None or v == "":
        return None
    return v


@bp.get("/customers")
def list_customers():
    return jsonify({"ok": True, "customers": foreign_customer_service.list_eligible_customers()})


@bp.get("/records")
def list_records():
    from flask import request

    month = request.args.get("month") or None
    customer_id = request.args.get("customer_id") or None
    records = foreign_customer_service.list_records(month=month, customer_id=customer_id)
    return jsonify({"ok": True, "records": records})


@bp.post("/records")
def add_record():
    body, err = parse_body(_RecordCreate)
    if err:
        return err
    try:
        record = foreign_customer_service.add_record(
            customer_id=body.customer_id,
            record_month=body.record_month,
            amount_due=body.amount_due,
            tax_number=_normalize_optional(body.tax_number),
            payment_date=_normalize_optional(body.payment_date),
            shipping_date=_normalize_optional(body.shipping_date),
            notes=_normalize_optional(body.notes),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 400
    return jsonify({"ok": True, "record": record})


@bp.put("/records/<int:record_id>")
def update_record(record_id: int):
    body, err = parse_body(_RecordUpdate)
    if err:
        return err
    try:
        record = foreign_customer_service.update_record(
            record_id,
            amount_due=body.amount_due,
            tax_number=_normalize_optional(body.tax_number),
            payment_date=_normalize_optional(body.payment_date),
            shipping_date=_normalize_optional(body.shipping_date),
            notes=_normalize_optional(body.notes),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "msg": str(exc)}), 404
    return jsonify({"ok": True, "record": record})


@bp.delete("/records/<int:record_id>")
def delete_record(record_id: int):
    removed = foreign_customer_service.delete_record(record_id)
    if not removed:
        return jsonify({"ok": False, "msg": "记录不存在"}), 404
    return jsonify({"ok": True})


@bp.get("/summary/<month>")
def summary(month: str):
    return jsonify({"ok": True, "summary": foreign_customer_service.month_summary(month)})
