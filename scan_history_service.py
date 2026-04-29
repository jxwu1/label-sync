"""扫描历史 service — 浏览 output/{员工}价格标{时间戳}/ 文件夹。

仅文件系统操作，不写 DB、不缓存（51 个 batch 的扫描 < 100ms）。
"""

import re

from config import CONFIG

OUTPUT_DIR = CONFIG.output_dir

_FOLDER_PATTERN = re.compile(r"^(?P<employee>.+?)价格标(?P<timestamp>\d{14})$")


def _parse_folder_name(name: str) -> dict | None:
    """从文件夹名抽员工 + 14 位时间戳。不匹配返回 None。"""
    m = _FOLDER_PATTERN.match(name)
    if not m:
        return None
    return {"employee": m.group("employee"), "timestamp": m.group("timestamp")}
