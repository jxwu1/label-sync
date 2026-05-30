"""PDA 扫描端 e2e 烟雾测试（opt-in，需先 `playwright install chromium`）。

流程（全程用沙箱 seed 的 admin/admin 账号，admin 也可进扫描端）：
  1. admin 登录
  2. 建一个 is_scanner 员工（PDA 操作员名单来源）
  3. 打开 /pda，选操作员，扫库位码 + 条码（扫描枪 = 键盘输入 + Enter），保存
  4. 回 PC 端，切「PDA 待处理」nav 页，断言该批次出现

注：第 4 步之后的「处理」会触发现有三阶段，依赖 stockpile 数据；沙箱无数据，
不在本烟雾范围（三阶段本身有自己的单元/集成测试）。

运行：
    playwright install chromium
    pytest e2e/test_pda_smoke.py
"""

_ALPINE_SETTLE_MS = 300


def _login(page, base_url: str, username: str, password: str) -> None:
    """通过 request 上下文登录（cookie 与同一 page 的后续导航共享）。"""
    resp = page.request.post(
        base_url + "/login", form={"username": username, "password": password}
    )
    assert resp.ok, f"登录失败 {resp.status}"


def _wait_alpine_ready(page) -> None:
    page.wait_for_function("window.Alpine !== undefined", timeout=5000)
    page.wait_for_timeout(_ALPINE_SETTLE_MS)


def test_pda_scan_to_pending_smoke(live_server, page_with_console) -> None:
    page = page_with_console
    base = live_server

    # 1. admin 登录（沙箱 _seed_admin 建的 admin/admin）
    _login(page, base, "admin", "admin")

    # 2. 建一个会扫描的员工（attendance 路由用 Pydantic 读 JSON body）
    created = page.request.post(base + "/attendance/employees", data={"name": "测试扫描员"})
    assert created.ok, f"建员工失败 {created.status}"
    emp_id = created.json()["employee"]["id"]
    flagged = page.request.post(
        base + f"/attendance/employees/{emp_id}/scanner", data={"is_scanner": True}
    )
    assert flagged.ok, f"标记 is_scanner 失败 {flagged.status}"

    # 3. 打开 PDA 扫描页（admin 已登录，扫描端对已登录用户开放）
    page.goto(base + "/pda")
    page.wait_for_selector("#opSelect", timeout=5000)

    # 选操作员（option value = employee_id）
    page.select_option("#opSelect", emp_id)
    page.wait_for_timeout(_ALPINE_SETTLE_MS)

    # 扫库位码 + 条码：扫描枪以"字符 + Enter"喂入隐藏的 #scanInput
    scan = page.locator("#scanInput")
    scan.fill("C08-12-03")
    scan.press("Enter")
    scan.fill("5828079343379")
    scan.press("Enter")
    page.wait_for_timeout(_ALPINE_SETTLE_MS)

    # 表格累积出 2 行（库位 + 条码）
    assert page.locator("#rows tr").count() >= 2

    # 保存（finalize 后前端 alert，提前挂 dialog 处理器自动确认）
    page.on("dialog", lambda d: d.accept())
    page.locator("#saveBtn").click()
    page.wait_for_timeout(_ALPINE_SETTLE_MS)

    # 4. PC 端：回首页，切「PDA 待处理」，断言批次出现
    page.goto(base + "/")
    _wait_alpine_ready(page)
    page.evaluate("Alpine.store('nav').switch('pda_pending')")
    page.locator("#pagePdaPending.active").wait_for(state="attached", timeout=3000)
    page.wait_for_timeout(_ALPINE_SETTLE_MS)

    assert "测试扫描员" in page.locator("#pdaPendingList").inner_text()
    assert page.console_errors == [], f"console errors: {page.console_errors}"
