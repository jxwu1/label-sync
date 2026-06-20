"""Dashboard 概览 stockpile 指标（库存 SKU / 停用 SKU / 上次导入）。

原 #spStats 4-数字面板**迁入 Dashboard**（不是退役）：数据走 /api/dashboard
（返回 sku/inactive/scans/lastImport，未初始化全 "—"），markup 改为 .dash-stat
（label + value，x-init fetch 填充）。

**单一转换测试**（未初始化 → 导入 → 已初始化）：e2e live_server 是 session 级共享
DB，拆成两个独立用例会让 import 写入泄漏、uninitialized 用例依赖执行顺序（逆序即挂）。
合并成一条状态转换即无此依赖。
"""

import re

_ALPINE_SETTLE_MS = 300


def _wait_alpine_ready(page) -> None:
    page.wait_for_function("window.Alpine !== undefined", timeout=5000)
    page.wait_for_timeout(_ALPINE_SETTLE_MS)


def _stat_value(page, label: str):
    """按 .dash-stat 的 label 文本取对应 .dash-stat-value locator。"""
    return page.locator(".dash-stat", has_text=label).locator(".dash-stat-value")


def _wait_stat(page, label: str, pattern: str) -> None:
    """等 label 对应的 .dash-stat-value 文本匹配 JS 正则（x-init fetch 完成后才稳定）。"""
    page.wait_for_function(
        "(() => { const s = [...document.querySelectorAll('.dash-stat')]"
        f".find(el => el.textContent.includes({label!r}));"
        " const v = s && s.querySelector('.dash-stat-value');"
        f" return !!(v && new RegExp({pattern!r}).test(v.textContent.trim())); }})()",
        timeout=5000,
    )


def test_dashboard_overview_uninitialized_then_initialized(live_server, page_with_console) -> None:
    """Dashboard stockpile 指标状态转换：未初始化显示 '—' → import → 显示数字 + 日期。"""
    page = page_with_console

    # 1) 未初始化：空 DB → /api/dashboard 返回 '—'
    page.goto(live_server + "/")
    _wait_alpine_ready(page)
    _wait_stat(page, "库存 SKU", "^—$")
    assert _stat_value(page, "库存 SKU").inner_text().strip() == "—"
    assert _stat_value(page, "停用 SKU").inner_text().strip() == "—"

    # 2) import 一份小 CSV
    csv_bytes = b"product_barcode,product_model,stockpile_location\nB1,M1,L1\nB2,M2,L2\nB3,M3,L3\n"
    resp = page.request.post(
        f"{live_server}/stockpile/init",
        multipart={"files": {"name": "init.csv", "mimeType": "text/csv", "buffer": csv_bytes}},
    )
    assert resp.ok, f"stockpile init failed: {resp.status} {resp.text()}"

    # 3) 已初始化：库存 SKU=3 / 停用=0 / 上次导入为日期
    page.goto(live_server + "/")
    _wait_alpine_ready(page)
    _wait_stat(page, "库存 SKU", r"^\d")
    assert _stat_value(page, "库存 SKU").inner_text().strip() == "3"
    assert _stat_value(page, "停用 SKU").inner_text().strip() == "0"
    # /api/dashboard 的 lastImport = last_import[:10] → 纯日期 YYYY-MM-DD
    last_import = _stat_value(page, "上次导入").inner_text().strip()
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", last_import), f"上次导入格式不对: {last_import!r}"

    assert page.console_errors == [], f"console errors: {page.console_errors}"
