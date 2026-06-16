"""API 响应 pydantic schema（前端独立化 spec §6）。

与 app/schemas.py（dataclass，进程内结构）分开：本模块只描述 HTTP API
契约，是 tools/gen_ts_types.py 的输入。新增 API 端点必须在此声明响应模型。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class BriefingCards(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sales_health: dict[str, Any]
    restock_risk: dict[str, Any]
    stockout_impact: dict[str, Any]
    overstock_risk: dict[str, Any]
    data_health: dict[str, Any]


class BriefingActions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    restock: dict[str, Any]
    follow_up: dict[str, Any]
    review_anomalies: dict[str, Any]


class BriefingData(BaseModel):
    """GET /api/briefing/data 响应。card/action 内层形状多态，v1 透传；
    前端组件消费到哪层，类型就加深到哪层（progressive typing）。"""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    generated_at: str
    data_week: str | None
    data_week_complete: bool
    cards: BriefingCards
    actions: BriefingActions


class MeData(BaseModel):
    display_name: str
    is_admin: bool


# gen_ts_types.py 的导出清单：新增模型加进来即自动进 types.gen.ts
API_MODELS: list[type[BaseModel]] = [BriefingData, MeData]
