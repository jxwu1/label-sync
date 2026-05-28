"""企业微信「打卡时间记录」xlsx 解析 + 考勤导入计划。

解析层为纯函数(无 DB);计划层只读 DB,核心逻辑 _build_plan_core 接受注入数据以便测试。
"""
import re
from io import BytesIO

import openpyxl

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
_PAREN_RE = re.compile(r"[(（][^)）]*[)）]")
_SPLIT_RE = re.compile(r"[、,，]")
_DAY_HEADER_RE = re.compile(r"^(\d{1,2})")
_FILENAME_DATE_RE = re.compile(r"(\d{4})(\d{2})\d{2}")

_HEADER_ROW = 3  # 0-based:列头在第 4 行
_NAME_COL = 0
_ACCOUNT_COL = 1


def parse_cell(text):
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


def detect_month(filename):
    """从文件名 (..._20260501-...) 推 'YYYY-MM';推不出返回 None。"""
    if not filename:
        return None
    m = _FILENAME_DATE_RE.search(filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def parse_workbook(xlsx_bytes, filename=""):
    """xlsx bytes → {'detected_month': 'YYYY-MM'|None, 'rows': [...]}。

    每行:{'account', 'name', 'days': {day_int: ('ok',s,e)|('single',t)}}。
    days 只含非空单元格;不计算日期(留给计划层按确认月份算)。
    """
    wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), read_only=True, data_only=True)
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
    for r in grid[_HEADER_ROW + 1:]:
        if not r:
            continue
        account = str(r[_ACCOUNT_COL]).strip() if len(r) > _ACCOUNT_COL and r[_ACCOUNT_COL] is not None else ""
        if not account:
            continue
        name = str(r[_NAME_COL]).strip() if len(r) > _NAME_COL and r[_NAME_COL] is not None else ""
        days = {}
        for ci, day in day_cols.items():
            parsed = parse_cell(r[ci] if ci < len(r) else None)
            if parsed[0] != "empty":
                days[day] = parsed
        rows.append({"account": account, "name": name, "days": days})
    wb.close()
    return {"detected_month": detect_month(filename), "rows": rows}
