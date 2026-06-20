"""旧 SPA（/，Alpine）浏览器烟雾：抓"页面打不开 / 切 tab 报 console 错 / Alpine 初始化挂"
这一类只有真浏览器才能发现的回归。Vue /ui/* 页见 test_ui_smoke.py。

运行：
    pytest e2e/            # 全部
    pytest e2e/ -m smoke   # 进 CI 的轻量子集

非烟雾的细粒度 UI 行为（点 X 后 Y 出现这种）不在本套范围内——roadmap 阶段 2
备忘已否过 Vitest store 单测；e2e 这一层只看冒烟。
"""

import pytest

# Alpine 用 queueMicrotask 延迟 init，给一点 settle 时间
_ALPINE_SETTLE_MS = 300


def _wait_alpine_ready(page) -> None:
    page.wait_for_function("window.Alpine !== undefined", timeout=5000)
    page.wait_for_timeout(_ALPINE_SETTLE_MS)


@pytest.mark.smoke
def test_index_loads_no_console_error(live_server, page_with_console) -> None:
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)
    assert page.title() != ""
    assert page.console_errors == [], f"console errors: {page.console_errors}"


# 旧 SPA 当前存活 nav 页（store.js pages 单源；history/sales_analytics/transfer 已退役）。
# store.pages 合法增删页时同步此处——这是显式漂移闸（误删存活页会变红）。
_EXPECTED_LIVE_PAGES = {
    "dashboard",
    "main",
    "dup",
    "purchase",
    "attendance",
    "data_quality",
    "inventory",
    "foreign_customers",
    "restock",
    "pda_pending",
    "admin",
}


@pytest.mark.smoke
def test_all_nav_pages_switch_no_console_error(live_server, page_with_console) -> None:
    """遍历 Alpine store 实际存活的 nav pages：逐个切换 → 该页 active + 无 console error。

    用 store.pages 运行时取集合（而非硬编码），退役/新增页自动跟随，不再漂移。
    """
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    nav_ids = page.evaluate("Alpine.store('nav').pages.map(p => p.id)")
    assert nav_ids, "Alpine store 没有任何 nav pages"
    # 显式存活集合守护：动态遍历能防"退役页残留"，但防不了"某存活入口被误删仍绿"。
    # 钉死期望集合 → 误删存活页 / 误加退役页都会在此变红（store.pages 合法变更时同步此处）。
    assert set(nav_ids) == _EXPECTED_LIVE_PAGES, (
        f"nav store.pages 与期望存活集合不符：多={set(nav_ids) - _EXPECTED_LIVE_PAGES} "
        f"少={_EXPECTED_LIVE_PAGES - set(nav_ids)}"
    )

    for nav_id in nav_ids:
        page.evaluate(f"Alpine.store('nav').switch('{nav_id}')")
        page.wait_for_function(f"Alpine.store('nav').current === '{nav_id}'", timeout=2000)
        # 切换后必有某个 .page.active（各页 DOM id 命名不一，不硬编码）
        page.locator(".page.active").first.wait_for(state="attached", timeout=2000)
        assert page.console_errors == [], (
            f"切到 {nav_id} 后出现 console errors: {page.console_errors}"
        )


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
    """侧栏折叠：store.collapsed 切换 + localStorage 持久化 + 真实 DOM 效果（折叠后
    `.sidebar-foot-label` 经 x-show 隐藏）。旧 SPA 侧栏无 `.is-collapsed` class（那是
    `.pnl` 折叠面板专用），折叠观感由 x-show 标签隐藏体现。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    assert page.evaluate("Alpine.store('nav').collapsed") is False
    assert page.locator(".sidebar-foot-label").is_visible()

    page.evaluate("Alpine.store('nav').toggleCollapse()")
    page.wait_for_timeout(_ALPINE_SETTLE_MS)

    assert page.evaluate("Alpine.store('nav').collapsed") is True
    assert page.evaluate("localStorage.getItem('nav.collapsed')") == "1"
    # 真实折叠效果：foot label 经 x-show="!collapsed" 隐藏
    assert page.locator(".sidebar-foot-label").is_hidden()
    assert page.console_errors == [], f"console errors: {page.console_errors}"


def test_clock_running(live_server, page_with_console) -> None:
    """PR-FE-1：实时时钟显示 HH:MM:SS。"""
    page = page_with_console
    page.goto(live_server + "/")
    _wait_alpine_ready(page)
    # 等 1.5s 看时钟应该被触发
    page.wait_for_timeout(1500)
    clock_text = page.locator(".header-clock").inner_text().strip()
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

    # 默认落地页 = dashboard
    assert page.evaluate("Alpine.store('nav').current") == "dashboard"

    # Ctrl+3 → purchase
    page.keyboard.press("Control+3")
    page.wait_for_timeout(_ALPINE_SETTLE_MS)
    assert page.evaluate("Alpine.store('nav').current") == "purchase"

    # Ctrl+8 → foreign_customers（原 Ctrl+9→sales_analytics 已随该页退役移除）
    page.keyboard.press("Control+8")
    page.wait_for_timeout(_ALPINE_SETTLE_MS)
    assert page.evaluate("Alpine.store('nav').current") == "foreign_customers"

    assert page.console_errors == [], f"console errors: {page.console_errors}"


# 货号历史已迁 Vue /ui/history（旧 SPA #pageHistory 退役）；其浏览器烟雾见 test_ui_smoke.py。
