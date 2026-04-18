import sys
from pathlib import Path
from typing import Any

import pandas as pd


def read_input_file(path: Path) -> pd.DataFrame | None:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, header=0, dtype=str)
    if suffix == ".csv":
        try:
            return pd.read_csv(path, dtype=str, encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(path, dtype=str, encoding="gbk")
    return None


def check_duplicates(filepath: str | Path) -> dict[str, Any]:
    """Check duplicate values in the first column of an uploaded file."""
    path = Path(filepath)
    dataframe = read_input_file(path)
    if dataframe is None:
        return {"ok": False, "msg": f"不支持的文件格式：{path.suffix.lower()}"}

    if dataframe.empty:
        return {"ok": True, "column": "", "total": 0, "dup_count": 0, "duplicates": []}

    first_column = dataframe.columns[0]
    values = dataframe[first_column].fillna("").str.strip()
    non_empty_values = values[values != ""]
    duplicate_values = non_empty_values[non_empty_values.duplicated(keep=False)]

    row_groups: dict[str, list[int]] = {}
    for row_index, value in duplicate_values.items():
        row_groups.setdefault(value, []).append(int(row_index) + 2)

    duplicates = [
        {"value": value, "rows": rows, "count": len(rows)}
        for value, rows in row_groups.items()
    ]
    duplicates.sort(key=lambda item: -item["count"])

    return {
        "ok": True,
        "column": first_column,
        "total": int(len(non_empty_values)),
        "dup_count": len(row_groups),
        "duplicates": duplicates,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法: python check_duplicates.py <文件路径>")
        return 1

    result = check_duplicates(argv[1])
    if not result["ok"]:
        print("错误:", result["msg"])
        return 1

    print(
        f"列名：{result['column']}  总条数：{result['total']}  重复值数：{result['dup_count']}"
    )
    for item in result["duplicates"]:
        print(f"  {item['value']}  出现 {item['count']} 次，行号：{item['rows']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
