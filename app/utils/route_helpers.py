"""HTTP 边界辅助：Pydantic 请求体解析 + 中文错误响应。

使用方法：

    from pydantic import BaseModel
    from app.utils.route_helpers import parse_body, NonEmptyStr

    class EmployeeCreate(BaseModel):
        name: NonEmptyStr

    @bp.post("/employees")
    def create_employee():
        body, err = parse_body(EmployeeCreate)
        if err:
            return err
        ...

错误响应保持现有格式 `{"ok": False, "msg": "..."}` + 400，前端无感知。
"""

from typing import Annotated, TypeVar

from flask import jsonify, request
from pydantic import BaseModel, BeforeValidator, ValidationError


def _stripped_nonempty(v: object) -> str:
    if not isinstance(v, str):
        raise ValueError("必须为字符串")
    s = v.strip()
    if not s:
        raise ValueError("不能为空")
    return s


def _stripped_optional(v: object) -> str:
    """允许 None / 空串，统一 strip。"""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ValueError("必须为字符串")
    return v.strip()


NonEmptyStr = Annotated[str, BeforeValidator(_stripped_nonempty)]
OptionalStr = Annotated[str, BeforeValidator(_stripped_optional)]


M = TypeVar("M", bound=BaseModel)


def parse_body(model_cls: type[M]) -> tuple[M | None, tuple | None]:
    """解析 + 校验请求体。返回 (model, None) 或 (None, (response, 400))。

    错误信息只取 ValidationError 的第一条，格式：`参数 <字段>：<原因>`。
    """
    data = request.get_json(silent=True) or {}
    try:
        return model_cls.model_validate(data), None
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "?"
        msg = first.get("msg") or "参数错误"
        return None, (jsonify({"ok": False, "msg": f"参数 {loc}：{msg}"}), 400)
