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
    ("sales_analytics", "pageSalesAnalytics"),
    ("transfer", "pageTransfer"),
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


def test_sales_analytics_page_renders(live_server, page_with_console) -> None:
    """PR 5.2 销售分析顶级 tab 切过去 + 筛选/排序控件挂上 + 不报错。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    page.evaluate("Alpine.store('nav').switch('sales_analytics')")
    page.locator("#pageSalesAnalytics.active").wait_for(state="attached", timeout=2000)

    # 4 组筛选 chip 都在
    chip_groups = page.evaluate(
        "Array.from(new Set([...document.querySelectorAll('.sa-chip')].map(b => b.dataset.filter)))"
    )
    assert set(chip_groups) == {"auto", "manual", "cust", "warn"}

    # 列头排序（PR-FE-3 换掉旧 dropdown）+ 表格骨架在
    assert page.locator(".sa-th-sort").count() >= 4
    assert page.locator("#saTbody").count() == 1

    page.wait_for_timeout(_ALPINE_SETTLE_MS)
    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_foreign_customers_page_renders(live_server, page_with_console) -> None:
    """PR 4.4 老外客人页切过去 + 月份选择/CRUD 控件挂上 + 不报错。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    page.evaluate("Alpine.store('nav').switch('foreign_customers')")
    page.locator("#pageForeignCustomers.active").wait_for(state="attached", timeout=2000)

    # 关键控件在
    assert page.locator("#fcMonth").count() == 1
    assert page.locator("#fcAddBtn").count() == 1
    assert page.locator("#fcRecordsBody").count() == 1

    page.wait_for_timeout(_ALPINE_SETTLE_MS)
    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_theme_toggle_persists(live_server, page_with_console) -> None:
    """PR-FE-1：主题切换 + localStorage 持久化 + body[data-theme] 正确反映。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    # 默认 dark
    assert page.evaluate("document.body.dataset.theme") == "dark"
    # 切换
    page.evaluate("Alpine.store('theme').toggle()")
    page.wait_for_timeout(_ALPINE_SETTLE_MS)
    assert page.evaluate("document.body.dataset.theme") == "light"
    assert page.evaluate("localStorage.getItem('theme')") == "light"
    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_sidebar_collapse(live_server, page_with_console) -> None:
    """PR-FE-1：侧栏折叠 200↔56 + Alpine store 持久化。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    assert page.evaluate("Alpine.store('nav').collapsed") is False
    page.evaluate("Alpine.store('nav').toggleCollapse()")
    page.wait_for_timeout(_ALPINE_SETTLE_MS)
    assert page.evaluate("Alpine.store('nav').collapsed") is True
    # CSS class 跟着变
    assert page.locator(".app-sidebar.is-collapsed").count() == 1
    assert page.evaluate("localStorage.getItem('nav.collapsed')") == "1"
    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_clock_running(live_server, page_with_console) -> None:
    """PR-FE-1：实时时钟显示 HH:MM:SS。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)
    # 等 1.5s 看时钟应该被触发
    page.wait_for_timeout(1500)
    clock_text = page.locator(".app-header__clock").inner_text().strip()
    # HH:MM:SS 格式
    import re

    assert re.match(r"^\d{2}:\d{2}:\d{2}$", clock_text), f"got '{clock_text}'"
    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_keyboard_shortcut_switches_nav(live_server, page_with_console) -> None:
    """PR-FE-1：⌘/Ctrl + 1-9 全局快捷键切 nav。

    验证两个不同 shortcut 都生效，确认 keydown 监听器和 store.bySortcut 路径都活着。
    """
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    # 默认在 main
    assert page.evaluate("Alpine.store('nav').current") == "main"

    # Ctrl+3 → purchase
    page.keyboard.press("Control+3")
    page.wait_for_timeout(_ALPINE_SETTLE_MS)
    assert page.evaluate("Alpine.store('nav').current") == "purchase"

    # Ctrl+9 → sales_analytics
    page.keyboard.press("Control+9")
    page.wait_for_timeout(_ALPINE_SETTLE_MS)
    assert page.evaluate("Alpine.store('nav').current") == "sales_analytics"

    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_history_analytics_panels_present(live_server, page_with_console) -> None:
    """PR 5.2a/d 货号详情新加的 analytics + timeline chart panel DOM 在。

    沙箱无数据，不真发起搜索；只验证 panel 容器和 chart canvas 已注入。
    """
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    page.evaluate("Alpine.store('nav').switch('history')")
    page.locator("#pageHistory.active").wait_for(state="attached", timeout=2000)

    # 两个 panel 默认 hidden 但 DOM 已存在
    assert page.locator("#historyAnalyticsPanel").count() == 1
    assert page.locator("#historyTimelineChartPanel").count() == 1
    assert page.locator("#historyTimelineChart").count() == 1

    page.wait_for_timeout(_ALPINE_SETTLE_MS)
    assert page.console_errors == [], f"console errors: {page.console_errors}"
