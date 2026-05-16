"""老外客人月度记录 service。

适用场景：批发场景里老外客户的赊账 / 税号 / 付款 / 托运记录。每月每客户一条
（UNIQUE 约束在 schema 层），用户在新 tab 里手动录入。

与销售事件的关系：通过 customer_id 关联 customers 表，但记录本身**与
inventory_events 解耦**（用户手动录入业务节点：欠款/付款/托运），不依赖事件
聚合。
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.repositories import stockpile_db
from app.models import Customer, ForeignCustomerRecord


def _record_to_dict(rec: ForeignCustomerRecord) -> dict:
    return {
        "id": rec.id,
        "customer_id": rec.customer_id,
        "record_month": rec.record_month,
        "amount_due": rec.amount_due,
        "tax_number": rec.tax_number,
        "payment_date": rec.payment_date,
        "shipping_date": rec.shipping_date,
        "notes": rec.notes,
        "created_at": rec.created_at,
    }


def list_eligible_customers() -> list[dict]:
    """返回老外客户列表（foreign / mixed / unknown 类型 + 中国客户都列上以防遗漏）。

    按 type 排序：foreign / mixed / unknown / chinese 顺序，每组按 customer_name 字典序。
    """
    type_order = {"foreign": 0, "mixed": 1, "unknown": 2, "chinese": 3}
    with stockpile_db._session() as session:
        rows = session.execute(
            select(Customer.customer_id, Customer.customer_name, Customer.customer_type)
        ).all()
    customers = [
        {
            "customer_id": r.customer_id,
            "customer_name": r.customer_name,
            "customer_type": r.customer_type,
        }
        for r in rows
    ]
    customers.sort(key=lambda c: (type_order.get(c["customer_type"], 99), c["customer_name"]))
    return customers


def list_records(month: str | None = None, customer_id: str | None = None) -> list[dict]:
    """筛选月份和/或客户。返回时按 record_month desc + customer_name asc 排序。"""
    with stockpile_db._session() as session:
        stmt = select(ForeignCustomerRecord, Customer.customer_name).join(
            Customer, Customer.customer_id == ForeignCustomerRecord.customer_id
        )
        if month:
            stmt = stmt.where(ForeignCustomerRecord.record_month == month)
        if customer_id:
            stmt = stmt.where(ForeignCustomerRecord.customer_id == customer_id)
        stmt = stmt.order_by(ForeignCustomerRecord.record_month.desc(), Customer.customer_name)
        rows = session.execute(stmt).all()
    out = []
    for rec, name in rows:
        d = _record_to_dict(rec)
        d["customer_name"] = name
        out.append(d)
    return out


def get_record(record_id: int) -> dict | None:
    with stockpile_db._session() as session:
        rec = session.get(ForeignCustomerRecord, record_id)
        if rec is None:
            return None
        d = _record_to_dict(rec)
        cust = session.get(Customer, rec.customer_id)
        d["customer_name"] = cust.customer_name if cust else ""
        return d


def add_record(
    customer_id: str,
    record_month: str,
    amount_due: float | None = None,
    tax_number: str | None = None,
    payment_date: str | None = None,
    shipping_date: str | None = None,
    notes: str | None = None,
) -> dict:
    """添加月度记录。同 (customer_id, record_month) 重复 → ValueError。"""
    with stockpile_db._session() as session:
        cust = session.get(Customer, customer_id)
        if cust is None:
            raise ValueError(f"客户 {customer_id} 不存在")
        rec = ForeignCustomerRecord(
            customer_id=customer_id,
            record_month=record_month,
            amount_due=amount_due,
            tax_number=tax_number,
            payment_date=payment_date,
            shipping_date=shipping_date,
            notes=notes,
        )
        session.add(rec)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(f"客户 {customer_id} 在 {record_month} 已有记录") from exc
        d = _record_to_dict(rec)
        d["customer_name"] = cust.customer_name
        return d


def update_record(record_id: int, **fields) -> dict:
    """部分更新。只更新传入的非 None 字段。"""
    allowed = {"amount_due", "tax_number", "payment_date", "shipping_date", "notes"}
    with stockpile_db._session() as session:
        rec = session.get(ForeignCustomerRecord, record_id)
        if rec is None:
            raise ValueError(f"记录 {record_id} 不存在")
        for k, v in fields.items():
            if k in allowed:
                setattr(rec, k, v)
        session.commit()
        d = _record_to_dict(rec)
        cust = session.get(Customer, rec.customer_id)
        d["customer_name"] = cust.customer_name if cust else ""
        return d


def delete_record(record_id: int) -> bool:
    """返回 True 如果删了一条，False 如果不存在。"""
    with stockpile_db._session() as session:
        rec = session.get(ForeignCustomerRecord, record_id)
        if rec is None:
            return False
        session.delete(rec)
        session.commit()
        return True


def month_summary(month: str) -> dict:
    """月度汇总：总欠款 / 已付 / 未付 / 已托运 / 记录数。"""
    records = list_records(month=month)
    total_due = sum(r["amount_due"] or 0 for r in records)
    paid = sum(1 for r in records if r["payment_date"])
    shipped = sum(1 for r in records if r["shipping_date"])
    return {
        "month": month,
        "record_count": len(records),
        "total_amount_due": total_due,
        "paid_count": paid,
        "unpaid_count": len(records) - paid,
        "shipped_count": shipped,
    }
