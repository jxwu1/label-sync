"""R1 第二块：holiday 导入后 cell 真渲染（不只看 class，看 computed style）。

抓"CSS 没加载 / specificity 被覆盖 / class 加了但视觉没变"这一类回归。**断言形式**：
- class 检查（DOM 层面）+ getComputedStyle dot opacity（CSS 真生效）双轨
- 用同月非假日 cell 做对照，确保差异是 holiday class 带来的、不是全局样式变化
- 选 2026-03-25 (Independence Day, 固定日期)，不依赖 Orthodox Easter 计算
"""

import pytest

_ALPINE_SETTLE_MS = 300


def _wait_alpine_ready(page) -> None:
    page.wait_for_function("window.Alpine !== undefined", timeout=5000)
    page.wait_for_timeout(_ALPINE_SETTLE_MS)


@pytest.fixture
def attendance_with_holidays(live_server, page_with_console):
    """在沙箱里建员工 + 导入 2026 希腊节假日。"""
    page = page_with_console
    emp_resp = page.request.post(
        f"{live_server}/attendance/employees",
        data='{"name": "节假日测试员工"}',
        headers={"Content-Type": "application/json"},
    )
    assert emp_resp.ok, f"create employee failed: {emp_resp.status} {emp_resp.text()}"

    hol_resp = page.request.post(f"{live_server}/attendance/holidays/import-year/2026")
    assert hol_resp.ok, f"holiday import failed: {hol_resp.status} {hol_resp.text()}"
    return page


def test_holiday_cell_visual_marker_after_import(live_server, attendance_with_holidays) -> None:
    page = attendance_with_holidays
    page.goto(live_server + "/")
    _wait_alpine_ready(page)

    page.evaluate("Alpine.store('nav').switch('attendance')")
    page.locator("#pageAttendance.active").wait_for(state="attached", timeout=2000)

    # 切到 2026-03（含 Independence Day）
    page.evaluate(
        """
        const m = document.getElementById('attnMonth');
        m.value = '2026-03';
        m.dispatchEvent(new Event('change'));
        """
    )

    holiday_cell = page.locator('.attn-cell[data-date="2026-03-25"]')
    holiday_cell.wait_for(state="visible", timeout=5000)

    # 1. DOM 层面：拿到 holiday class
    cls = holiday_cell.get_attribute("class") or ""
    assert "attn-cell--holiday" in cls, f"expected holiday class, got: {cls}"

    # 2. CSS 真生效：dot opacity ≈ 0.4（被 .attn-cell--holiday .attn-cell-dot 规则覆盖）
    #    若 CSS 文件没加载 / specificity 被覆盖，opacity 会是 1 (浏览器默认)
    dot_opacity = holiday_cell.locator(".attn-cell-dot").evaluate(
        "el => getComputedStyle(el).opacity"
    )
    assert abs(float(dot_opacity) - 0.4) < 0.01, f"holiday dot opacity={dot_opacity}, 期望 ≈0.4"

    # 3. CSS 真生效：cursor 是 default（不是 pointer，区分于普通可点 cell）
    cursor = holiday_cell.evaluate("el => getComputedStyle(el).cursor")
    assert cursor == "default", f"holiday cursor 应该是 'default', got '{cursor}'"

    # 4. 同月非假日 cell 对照：2026-03-03 (周二) dot opacity 应该是 1
    #    employee 无 start_date → 该天为 absent (workday past)，dot 是 --error 全不透
    normal_cell = page.locator('.attn-cell[data-date="2026-03-03"]')
    normal_cell.wait_for(state="visible", timeout=2000)
    normal_opacity = normal_cell.locator(".attn-cell-dot").evaluate(
        "el => getComputedStyle(el).opacity"
    )
    assert float(normal_opacity) >= 0.99, f"非假日 cell dot opacity 应该 ≈1, got {normal_opacity}"

    assert page.console_errors == [], f"console errors: {page.console_errors}"
