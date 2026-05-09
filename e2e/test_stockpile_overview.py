"""Stream A：数据仓库 panel 状态 tab 4 数字 mini stat 进首页就显示。

抓的是只有真浏览器才能验的：
- HTML 结构 + CSS 真生效（4 个数字真渲染、布局正确）
- 进首页（不切页）就 fetch + 显示，不需要 import 触发
- initialized vs uninitialized 状态切换（spStats / spStatus 互斥显示）
"""

_ALPINE_SETTLE_MS = 300


def _wait_alpine_ready(page) -> None:
    page.wait_for_function("window.Alpine !== undefined", timeout=5000)
    page.wait_for_timeout(_ALPINE_SETTLE_MS)


def test_stockpile_panel_uninitialized_shows_hint(live_server, page_with_console) -> None:
    """沙箱空 DB → spStats 隐藏，spStatus 显示「未初始化」提示。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    # 进首页就 fetch /stockpile/status，等响应稳定
    page.wait_for_function(
        "document.getElementById('spStatus').textContent.includes('未初始化') "
        "|| document.getElementById('spStatus').textContent.includes('检查失败')",
        timeout=5000,
    )

    # spStats 应该 hidden（uninitialized 不显示 4 数字）
    assert page.locator("#spStats").is_hidden()
    # spStatus 应该 visible 并显示「未初始化」
    assert page.locator("#spStatus").is_visible()
    text = page.locator("#spStatus").inner_text()
    assert "未初始化" in text, f"expected 未初始化 hint, got: {text}"

    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_stockpile_panel_initialized_shows_4_stats(live_server, page_with_console) -> None:
    """import 数据 → 进首页 → 4 数字 mini stats 全部填好，spStatus 隐藏。"""
    page = page_with_console

    # 沙箱内 import 一份小 CSV
    csv_bytes = b"product_barcode,product_model,stockpile_location\nB1,M1,L1\nB2,M2,L2\nB3,M3,L3\n"
    resp = page.request.post(
        f"{live_server}/stockpile/init",
        multipart={"files": {"name": "init.csv", "mimeType": "text/csv", "buffer": csv_bytes}},
    )
    assert resp.ok, f"stockpile init failed: {resp.status} {resp.text()}"

    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    # 4 数字 mini stats 出现（initialized 路径）
    page.locator("#spStats").wait_for(state="visible", timeout=5000)
    assert page.locator("#spStatus").is_hidden(), "uninitialized hint 应该隐藏"

    # 总条数 = 3
    assert page.locator("#spStatTotal").inner_text() == "3"
    # 活跃 = 3, 失效 = 0
    assert page.locator("#spStatActive").inner_text() == "3"
    assert page.locator("#spStatInactive").inner_text() == "0"
    # 上次 import 应该匹配 "YYYY-MM-DD HH:MM" 格式（不带秒，user 选的）
    last_import = page.locator("#spStatLastImport").inner_text()
    import re

    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", last_import), (
        f"last_import 格式不对: {last_import!r}"
    )

    # CSS 真生效：sp-stat-num 应该用 mono 字体 + accent 色（不是默认 ink-0）
    num_color = page.locator("#spStatTotal").evaluate("el => getComputedStyle(el).color")
    # accent 在 dark theme 是 #00ff95-ish；不绑死颜色值，但应该不是默认黑/白
    assert num_color not in ("rgb(0, 0, 0)", "rgb(255, 255, 255)"), (
        f"sp-stat-num 颜色看起来没应用 accent: {num_color}"
    )

    assert page.console_errors == [], f"console errors: {page.console_errors}"
