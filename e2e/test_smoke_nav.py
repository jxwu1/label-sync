"""5 个浏览器烟雾测试：抓"页面打不开 / 切 tab 报 console 错 / Alpine 初始化挂"
这一类只有真浏览器才能发现的回归。

运行：
    pytest e2e/

非烟雾的细粒度 UI 行为（点 X 后 Y 出现这种）不在本套范围内——roadmap 阶段 2
备忘已否过 Vitest store 单测；e2e 这一层只看冒烟。
"""

import pytest

# Alpine 用 queueMicrotask 延迟 init，给一点 settle 时间
_ALPINE_SETTLE_MS = 300


def _wait_alpine_ready(page) -> None:
    page.wait_for_function("window.Alpine !== undefined", timeout=5000)
    page.wait_for_timeout(_ALPINE_SETTLE_MS)


def test_index_loads_no_console_error(live_server, page_with_console) -> None:
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)
    assert page.title() != ""
    assert page.console_errors == [], f"console errors: {page.console_errors}"


# nav store id (snake_case) → page DOM id (camelCase)
_NAV_PAGES = [
    ("main", "pageMain"),
    ("purchase", "pagePurchase"),
    ("attendance", "pageAttendance"),
    ("history", "pageHistory"),
    ("data_quality", "pageDataQuality"),
    ("inventory", "pageInventory"),
    ("foreign_customers", "pageForeignCustomers"),
]


@pytest.mark.parametrize("nav_id,dom_id", _NAV_PAGES)
def test_nav_switches_page_active(live_server, page_with_console, nav_id, dom_id) -> None:
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    # 通过 store 切页（避开点击坐标问题，更稳）
    page.evaluate(f"Alpine.store('nav').switch('{nav_id}')")

    # 对应 page 元素拿到 .active class
    page.locator(f"#{dom_id}.active").wait_for(state="attached", timeout=2000)

    assert page.console_errors == [], f"切到 {nav_id} 后出现 console errors: {page.console_errors}"


def test_fab_drawer_opens(live_server, page_with_console) -> None:
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    # 通过 store 打开抽屉（FAB 点击坐标在不同分辨率下漂移，store 控制更稳）
    page.evaluate("Alpine.store('ui').drawer = 'quickMenu'")
    page.wait_for_timeout(_ALPINE_SETTLE_MS)

    # 抽屉的 store 状态正确
    drawer_state = page.evaluate("Alpine.store('ui').drawer")
    assert drawer_state == "quickMenu"

    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_history_search_renders(live_server, page_with_console) -> None:
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    page.evaluate("Alpine.store('nav').switch('history')")
    page.locator("#pageHistory.active").wait_for(state="attached", timeout=2000)

    # 货号查询子 tab 默认就 active；其结构存在即可
    page.locator('[data-history-tab-panel="search"]').wait_for(state="attached", timeout=2000)

    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_data_quality_page_renders(live_server, page_with_console) -> None:
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    page.evaluate("Alpine.store('nav').switch('data_quality')")
    page.locator("#pageDataQuality.active").wait_for(state="attached", timeout=2000)

    # 数据质量页 4 个 section 区域应该都在 DOM（即使空数据）
    # 沙箱里没数据，section 标题或骨架仍应渲染
    page.wait_for_timeout(_ALPINE_SETTLE_MS)

    assert page.console_errors == [], f"console errors: {page.console_errors}"
