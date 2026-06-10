"""数据新鲜度判定 (split-only 拆分自 analytics)。"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.models import InventoryEvent, SystemSetting
from app.repositories import stockpile_db
from app.services.analytics._shared import _parse_date, _today

# 数据新鲜度: scraper 每周抓一次, 距上次灌数 > 9 天 → 至少漏了一轮, 判定 stale
_DATA_STALE_DAYS = 9

# 抓取成功心跳: 抓取器每周成功跑完打一次 (写 SystemSetting)。距上次心跳 > 8 天
# (周抓 7 + 1 缓冲, 比数据龄 9 天更早暴露) → 判定抓取可能中断。
SCRAPE_STALE_DAYS = 8
HEARTBEAT_KEY = "scrape:last_success_at"


def get_data_freshness(as_of: date | None = None) -> dict[str, Any]:
    """返回数据新鲜度: 数据龄(imported_at) + 抓取心跳(scrape:last_success_at)。

    {last_import_at, last_import_date, days_since, stale,
     last_scrape_success_at, scrape_days_since, scrape_stale}
    空库 / 空心跳 → 对应字段 None + 对应 stale=False (新系统/本地不误报)。
    """
    as_of = as_of or _today()
    with stockpile_db._session() as session:
        last = session.execute(select(func.max(InventoryEvent.imported_at))).scalar()
        hb = session.get(SystemSetting, HEARTBEAT_KEY)

    hb_val = hb.value if hb else None
    if hb_val:
        # 只按日期算 (UTC ISO 取前 10 字符 → date), 避免时区细节影响 UI。
        scrape_date = _parse_date(hb_val)
        scrape_days_since: int | None = (as_of - scrape_date).days
        scrape_stale = scrape_days_since > SCRAPE_STALE_DAYS
    else:
        scrape_days_since = None
        scrape_stale = False

    if not last:
        return {
            "last_import_at": None,
            "last_import_date": None,
            "days_since": None,
            "stale": False,
            "last_scrape_success_at": hb_val,
            "scrape_days_since": scrape_days_since,
            "scrape_stale": scrape_stale,
        }
    last_date = _parse_date(str(last))
    days = (as_of - last_date).days
    return {
        "last_import_at": str(last),
        "last_import_date": last_date.isoformat(),
        "days_since": days,
        "stale": days > _DATA_STALE_DAYS,
        "last_scrape_success_at": hb_val,
        "scrape_days_since": scrape_days_since,
        "scrape_stale": scrape_stale,
    }
