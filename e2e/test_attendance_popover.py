"""R1 第一块：attendance cell 点击 → popover 真 visible + bbox 在 viewport 内。

抓 PR-FE-7b 那一类回归（CSS specificity / Alpine 时序）。**断言形式**是关键：
- 用 `pop.wait_for(state="visible")`：Playwright 真算 CSS 层叠 + computed visibility，
  不会被「class 还在但 display:none」骗到（PR-FE-7b 当年踩的就是 class includes 检查）
- 用 `pop.bounding_box()` + viewport 比较：`positionPopover` 的位置算法跑错时
  bbox 会越界（顶/左为负 / 右/底超 viewport），class 检查抓不到这个
"""

import pytest

_ALPINE_SETTLE_MS = 300


def _wait_alpine_ready(page) -> None:
    page.wait_for_function("window.Alpine !== undefined", timeout=5000)
    page.wait_for_timeout(_ALPINE_SETTLE_MS)


@pytest.fixture
def employee_in_sandbox(live_server, page_with_console):
    """先在沙箱建一个员工，否则 attendance 页 cells 不渲染。"""
    resp = page_with_console.request.post(
        f"{live_server}/attendance/employees",
        data='{"name": "测试员工"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, f"create employee failed: {resp.status} {resp.text()}"
    return page_with_console


def test_attendance_popover_visible_and_within_viewport(live_server, employee_in_sandbox) -> None:
    page = employee_in_sandbox
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    page.evaluate("Alpine.store('nav').switch('attendance')")
    page.locator("#pageAttendance.active").wait_for(state="attached", timeout=2000)

    # 找一个真可点的 cell：排除上下月留白 / 入职前 / 周日 / 节假日
    cell = page.locator(
        ".attn-cell[data-date]"
        ":not(.attn-cell--out)"
        ":not(.attn-cell--pre-join)"
        ":not(.attn-cell--sunday)"
        ":not(.attn-cell--holiday)"
    ).first
    cell.wait_for(state="visible", timeout=5000)
    cell.click()

    # 真 visibility（Playwright 算 computed style，不是 class 字面量）
    pop = page.locator("#attnPop")
    pop.wait_for(state="visible", timeout=2000)

    # bbox 在 viewport 内 —— positionPopover 的位置算法回归会越界
    bbox = pop.bounding_box()
    viewport = page.viewport_size
    assert bbox is not None, "popover 拿不到 bounding box"
    assert bbox["width"] > 0 and bbox["height"] > 0, f"popover 尺寸异常: {bbox}"
    assert bbox["x"] >= 0, f"popover 越左: x={bbox['x']}"
    assert bbox["y"] >= 0, f"popover 越顶: y={bbox['y']}"
    assert bbox["x"] + bbox["width"] <= viewport["width"], (
        f"popover 越右: x+w={bbox['x'] + bbox['width']} > {viewport['width']}"
    )
    assert bbox["y"] + bbox["height"] <= viewport["height"], (
        f"popover 越底: y+h={bbox['y'] + bbox['height']} > {viewport['height']}"
    )

    assert page.console_errors == [], f"console errors: {page.console_errors}"
