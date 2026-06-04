"""企业微信「打卡时间记录」xlsx 解析 + 考勤导入计划。

解析层为纯函数(无 DB);计划层只读 DB,核心逻辑 _build_plan_core 接受注入数据以便测试。
"""

import json
import re
from io import BytesIO

import openpyxl
from sqlalchemy import select, update

from app.models import Employee, SystemSetting, get_session
from app.services import attendance as attendance_service

_TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})")
_PAREN_RE = re.compile(r"[(（][^)）]*[)）]")
_SPLIT_RE = re.compile(r"[、,，]")
_DAY_HEADER_RE = re.compile(r"^(\d{1,2})")
_FILENAME_DATE_RE = re.compile(r"(\d{4})(\d{2})\d{2}")

_HEADER_ROW = 3  # 0-based:列头在第 4 行
_NAME_COL = 0
_ACCOUNT_COL = 1


def parse_cell(text: object) -> tuple:
    """单元格 → ('ok', start, end) | ('single', t) | ('empty',)。

    去注释 → 按 、/, 拆 → 抓 HH:MM → 去重排序;0 个 empty,1 个 single,≥2 个 min/max。
    """
    if text is None:
        return ("empty",)
    s = str(text).strip()
    if not s or s == "--":
        return ("empty",)
    s = _PAREN_RE.sub("", s)
    times = []
    for tok in _SPLIT_RE.split(s):
        m = _TIME_RE.search(tok)
        if m:
            times.append(f"{int(m.group(1)):02d}:{int(m.group(2)):02d}")
    uniq = sorted(set(times))
    if not uniq:
        return ("empty",)
    if len(uniq) == 1:
        return ("single", uniq[0])
    return ("ok", uniq[0], uniq[-1])


def detect_month(filename: str | None) -> str | None:
    """从文件名 (..._20260501-...) 推 'YYYY-MM';推不出返回 None。"""
    if not filename:
        return None
    m = _FILENAME_DATE_RE.search(filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def parse_workbook(xlsx_bytes: bytes, filename: str = "") -> dict:
    """xlsx bytes → {'detected_month': 'YYYY-MM'|None, 'rows': [...]}。

    每行:{'account', 'name', 'days': {day_int: ('ok',s,e)|('single',t)}}。
    days 只含非空单元格;不计算日期(留给计划层按确认月份算)。
    """
    wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        grid = list(ws.iter_rows(values_only=True))
        header = grid[_HEADER_ROW] if len(grid) > _HEADER_ROW else ()
        day_cols = {}
        for ci, cell in enumerate(header):
            if cell is None:
                continue
            txt = str(cell).strip()
            if "星期" in txt:
                m = _DAY_HEADER_RE.match(txt)
                if m:
                    day_cols[ci] = int(m.group(1))
        rows = []
        for r in grid[_HEADER_ROW + 1 :]:
            if not r:
                continue
            raw_acct = r[_ACCOUNT_COL] if len(r) > _ACCOUNT_COL else None
            account = str(raw_acct).strip() if raw_acct is not None else ""
            if not account:
                continue
            raw_name = r[_NAME_COL] if len(r) > _NAME_COL else None
            name = str(raw_name).strip() if raw_name is not None else ""
            days = {}
            for ci, day in day_cols.items():
                parsed = parse_cell(r[ci] if ci < len(r) else None)
                if parsed[0] != "empty":
                    days[day] = parsed
            rows.append({"account": account, "name": name, "days": days})
    finally:
        wb.close()
    return {"detected_month": detect_month(filename), "rows": rows}


_IGNORE_KEY = "wecom_ignored_accounts"


def get_account_map() -> dict:
    """account -> employee_id(仅取已设 wecom_account 的员工)。"""
    with get_session() as s:
        rows = s.execute(
            select(Employee.wecom_account, Employee.employee_id).where(
                Employee.wecom_account.isnot(None)
            )
        ).all()
    return {acc: eid for acc, eid in rows if acc}


def bind_account(account: str, employee_id: str) -> None:
    """把账号绑到员工(1:1:先把该账号从其他员工清掉)。员工不存在 → ValueError。"""
    with get_session() as s:
        emp = s.get(Employee, employee_id)
        if not emp:
            raise ValueError(f"员工不存在：{employee_id}")
        s.execute(
            update(Employee).where(Employee.wecom_account == account).values(wecom_account=None)
        )
        emp.wecom_account = account


def list_ignored() -> set:
    """忽略账号集合(存在 SystemSetting 的 JSON list)。"""
    with get_session() as s:
        st = s.get(SystemSetting, _IGNORE_KEY)
        if not st or not st.value:
            return set()
        try:
            return set(json.loads(st.value))
        except (ValueError, TypeError):
            return set()


def ignore_account(account: str) -> None:
    """把账号加入忽略清单。"""
    accs = list_ignored()
    accs.add(account)
    payload = json.dumps(sorted(accs), ensure_ascii=False)
    with get_session() as s:
        st = s.get(SystemSetting, _IGNORE_KEY)
        if st:
            st.value = payload
        else:
            s.add(SystemSetting(key=_IGNORE_KEY, value=payload))


def unignore_account(account: str) -> None:
    """从忽略清单移除一个账号(不存在则 no-op)。"""
    accs = list_ignored()
    accs.discard(account)
    payload = json.dumps(sorted(accs), ensure_ascii=False)
    with get_session() as s:
        st = s.get(SystemSetting, _IGNORE_KEY)
        if st:
            st.value = payload
        else:
            s.add(SystemSetting(key=_IGNORE_KEY, value=payload))


def _build_plan_core(rows, month, *, account_map, ignored, name_by_id, month_data, leaves_by_emp):
    """纯计算计划核心。共享数据由调用方注入(便于测试)。"""
    # 姓名 -> employee_id 建议(仅唯一姓名才建议,重名留空)
    name_counts = {}
    for nm in name_by_id.values():
        name_counts[nm] = name_counts.get(nm, 0) + 1
    id_by_name = {nm: eid for eid, nm in name_by_id.items() if name_counts[nm] == 1}

    matched = []
    unbound = []
    needs_manual = []
    ignored_rows = []
    for row in rows:
        acc = row["account"]
        nm = row["name"]
        if acc in ignored:
            ignored_rows.append({"account": acc, "name": nm})
            continue
        eid = account_map.get(acc)
        if not eid:
            unbound.append(
                {"account": acc, "name": nm, "suggested_employee_id": id_by_name.get(nm)}
            )
            continue
        disp = name_by_id.get(eid, nm)
        existing = month_data.get(eid, {})
        leaves = leaves_by_emp.get(eid, {})
        to_write = []
        skip_existing = 0
        skip_single = 0
        for day_int in sorted(row["days"]):
            parsed = row["days"][day_int]
            date = f"{month}-{day_int:02d}"
            if date in existing or date in leaves:
                skip_existing += 1
                continue
            if parsed[0] == "single":
                skip_single += 1
                needs_manual.append(
                    {"employee_id": eid, "name": disp, "date": date, "time": parsed[1]}
                )
                continue
            _, start, end = parsed
            if start >= end:  # 异常时段,转手动
                skip_single += 1
                needs_manual.append(
                    {"employee_id": eid, "name": disp, "date": date, "time": f"{start}-{end}"}
                )
                continue
            to_write.append({"date": date, "start": start, "end": end})
        matched.append(
            {
                "employee_id": eid,
                "name": disp,
                "to_write": to_write,
                "skip_existing": skip_existing,
                "skip_single": skip_single,
            }
        )
    return {
        "month": month,
        "matched": matched,
        "unbound": unbound,
        "needs_manual": needs_manual,
        "ignored": ignored_rows,
        "counts": {
            "matched": len(matched),
            "unbound": len(unbound),
            "needs_manual": len(needs_manual),
            "to_write": sum(len(m["to_write"]) for m in matched),
            "ignored": len(ignored_rows),
        },
    }


def build_plan(rows, month):
    """读 DB(绑定/忽略/已有考勤/请假)并产出导入计划。"""
    employees = attendance_service.list_employees()
    name_by_id = {e["id"]: e["name"] for e in employees}
    return _build_plan_core(
        rows,
        month,
        account_map=get_account_map(),
        ignored=list_ignored(),
        name_by_id=name_by_id,
        month_data=attendance_service.load_month(month),
        leaves_by_emp=attendance_service.list_leaves(month),
    )


def apply_plan(rows, month):
    """对计划里的 to_write 天调 set_day 写入。返回写入/跳过计数。"""
    plan = build_plan(rows, month)
    written = 0
    for m in plan["matched"]:
        for d in m["to_write"]:
            attendance_service.set_day(
                m["employee_id"], d["date"], {"start": d["start"], "end": d["end"]}
            )
            written += 1
    return {
        "written": written,
        "skipped_existing": sum(m["skip_existing"] for m in plan["matched"]),
        "skipped_single": sum(m["skip_single"] for m in plan["matched"]),
        "unbound": len(plan["unbound"]),
    }
