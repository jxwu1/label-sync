"""pydantic JSON Schema → TypeScript 类型生成（自写轻量版，不引重型生成器）。

用法:
    python tools/gen_ts_types.py                 # 写 frontend/src/api/types.gen.ts
    python tools/gen_ts_types.py --check         # 漂移检查（CI 用，不一致退出码 1）
    python tools/gen_ts_types.py --out <path>    # 测试用自定义输出
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "frontend" / "src" / "api" / "types.gen.ts"
HEADER = "// 由 tools/gen_ts_types.py 生成 — 不要手改。来源: app/schemas_api.py\n\n"


def _ts_type(prop: dict, defs: dict) -> str:
    if "$ref" in prop:
        return prop["$ref"].split("/")[-1]
    if "anyOf" in prop:
        seen: list[str] = []
        for p in prop["anyOf"]:
            t = _ts_type(p, defs)
            if t not in seen:
                seen.append(t)
        return " | ".join(seen)
    t = prop.get("type")
    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "array":
        return f"{_ts_type(prop.get('items', {}), defs)}[]"
    if t == "object":
        return "Record<string, unknown>"
    return "unknown"


def _interface(name: str, schema: dict, defs: dict) -> str:
    lines = [f"export interface {name} {{"]
    required = set(schema.get("required", []))
    for field, prop in (schema.get("properties") or {}).items():
        opt = "" if field in required else "?"
        lines.append(f"  {field}{opt}: {_ts_type(prop, defs)};")
    lines.append("}\n")
    return "\n".join(lines)


def generate() -> str:
    from app.schemas_api import API_MODELS

    blocks: list[str] = []
    emitted: set[str] = set()
    for model in API_MODELS:
        schema = model.model_json_schema()
        defs = schema.pop("$defs", {})
        for ref_name, ref_schema in defs.items():
            if ref_name not in emitted:
                emitted.add(ref_name)
                blocks.append(_interface(ref_name, ref_schema, defs))
        name = schema.get("title", model.__name__)
        if name not in emitted:
            emitted.add(name)
            blocks.append(_interface(name, schema, defs))
    return HEADER + "\n".join(blocks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    text = generate()
    if args.check:
        if not out.exists() or out.read_text(encoding="utf-8") != text:
            print(f"types.gen.ts 与 app/schemas_api.py 不一致，重跑 gen_ts_types.py: {out}")
            return 1
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
