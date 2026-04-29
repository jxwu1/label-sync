STORE_PREFIXES = {"A", "B", "C"}
WAREHOUSE_PREFIXES = {"X", "Z"}

# 多库位子表分类用：异常前缀回退到 "unknown"，UI 单独栏展示
_KIND_BY_PREFIX: dict[str, str] = {
    **{p: "store" for p in STORE_PREFIXES},
    **{p: "warehouse" for p in WAREHOUSE_PREFIXES},
}


def classify_location(location: str) -> str | None:
    if not location:
        return None
    prefix = location[:1].upper()
    if prefix in STORE_PREFIXES:
        return "store"
    if prefix in WAREHOUSE_PREFIXES:
        return "warehouse"
    return None


def classify_kind(location: str) -> str:
    """子表用：返回 store / warehouse / unknown，不返回 None。"""
    if not location:
        return "unknown"
    return _KIND_BY_PREFIX.get(location[:1].upper(), "unknown")


def parse_to_locations(raw: str | None) -> list[dict]:
    """把 raw 字符串（如 "A22-04-04/XB04-16/XB04-17"）拆成子表行。

    返回 list[{"location": str, "kind": str, "position": int}]。
    - position 按源字符串顺序 0,1,2,...（保留店面在前/仓库在后约定）
    - 异常前缀 → kind="unknown"
    - 段间空白 strip；空段忽略
    """
    if not raw:
        return []
    result = []
    position = 0
    for part in str(raw).split("/"):
        loc = part.strip()
        if not loc:
            continue
        result.append({
            "location": loc,
            "kind": classify_kind(loc),
            "position": position,
        })
        position += 1
    return result


def categorize_locations(locations: list[str]) -> tuple[list[str], list[str], str | None]:
    cleaned = [location.strip() for location in locations if location and location.strip()]
    stores: list[str] = []
    warehouses: list[str] = []
    for location in cleaned:
        category = classify_location(location)
        if category is None:
            return [], [], f"unknown location prefix: {location}"
        if category == "store":
            if location not in stores:
                stores.append(location)
        else:
            if location not in warehouses:
                warehouses.append(location)
    return stores, warehouses, None


def parse_locations(locations: list[str]) -> tuple[str | None, str | None, str | None]:
    stores, warehouses, error = categorize_locations(locations)
    if error:
        return None, None, error
    if not stores and not warehouses:
        return None, None, None
    if len(stores) > 1 or len(warehouses) > 1:
        parts = []
        if stores:
            parts.append(f"store=[{','.join(stores)}]")
        if warehouses:
            parts.append(f"warehouse=[{','.join(warehouses)}]")
        return None, None, f"duplicate_locations {' '.join(parts)}"
    return (
        stores[0] if stores else None,
        warehouses[0] if warehouses else None,
        None,
    )


def parse_system_location(value: str) -> tuple[str | None, str | None, str | None]:
    raw = str(value or "").strip()
    if not raw or raw == "nan":
        return None, None, None
    parts = raw.split("/")
    if any(not part.strip() for part in parts):
        return None, None, f"invalid system location: {raw}"
    return parse_locations(parts)


def compose_location(
    old_store: str | None,
    old_warehouse: str | None,
    new_store: str | None,
    new_warehouse: str | None,
) -> str:
    final_store = new_store or old_store
    final_warehouse = new_warehouse or old_warehouse
    if final_store and final_warehouse:
        return f"{final_store}/{final_warehouse}"
    return final_store or final_warehouse or ""


def categorize_stockpile(raw: str) -> tuple[list[str], list[str], str | None]:
    text = str(raw or "").strip()
    if not text or text == "nan":
        return [], [], None
    parts = text.split("/")
    if any(not part.strip() for part in parts):
        return [], [], f"invalid system location: {text}"
    return categorize_locations(parts)


def compose_if_single(
    stockpile_stores: list[str],
    stockpile_warehouses: list[str],
    scan_stores: list[str],
    scan_warehouses: list[str],
) -> str:
    store = (scan_stores[0] if scan_stores else None) or (
        stockpile_stores[0] if stockpile_stores else None
    )
    warehouse = (scan_warehouses[0] if scan_warehouses else None) or (
        stockpile_warehouses[0] if stockpile_warehouses else None
    )
    return compose_location(None, None, store, warehouse)