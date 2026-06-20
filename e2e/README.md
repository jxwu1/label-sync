# E2E 浏览器烟雾测试

抓"页面打不开 / 切 tab 报 console 错 / Alpine 初始化挂 / Vue 页加载崩"这一类
**只有真浏览器才能发现**的回归。不写细粒度 UI 行为（roadmap 阶段 2 备忘已否过
Vitest store 单测；e2e 只看冒烟）。

覆盖两套前端：① 旧 SPA（`/`，Alpine，由 Flask 直接 serve）；② 新 Vue 页
（`/ui/briefing`、`/ui/forecast-eval`、`/ui/history`，测试 harness 把 `frontend/dist`
挂到 `/ui/*` 同源 serve）。**登录态**：`page_with_console` 依赖 `logged_in_page`，
用 seed admin（admin/admin）自动登录，所有用例自带 session，不会撞登录墙。

## 一次性安装

```sh
pip install -r requirements-dev.txt
playwright install chromium
```

`playwright install` 会下载 ~150MB Chromium 到本地缓存（默认
`~/.cache/ms-playwright/`）。装完一次就好。

## 跑

`/ui/*` 烟雾要先构建前端（`frontend/dist` 被 gitignore）。**标准命令**：

```sh
cd frontend && npm run build && cd ..   # 出 frontend/dist（/ui smoke 前置）
pytest e2e/                  # 全部 e2e（dist 缺失时 /ui 用例自动 skip，不报错）
pytest e2e/ -m smoke         # 只跑进 CI 的轻量 smoke 子集
pytest e2e/ --headed         # 看着浏览器跑（调试用）
pytest e2e/ -k nav --headed  # 只看 nav 那批
```

> 不构建 dist 直接 `pytest e2e/` 不是"自包含"——`/ui/*` 用例会以
> "frontend/dist 未构建" 为由 skip。要验 Vue 页必须先 `npm run build`。

## 默认不进 `pytest -q`

`e2e/` 没在 `pyproject.toml` 的 `testpaths` 里，所以日常 `pytest -q` 会跳过它，
不会变慢。要跑 e2e 必须显式 `pytest e2e/`。

## CI

轻量 smoke 子集（标 `@pytest.mark.smoke`：首页 + nav 遍历 + 三个 Vue 页加载）进 CI
独立 `e2e-smoke` job——装 Chromium + 构建前端 dist + `pytest e2e/ -m smoke`。其余较重
/不稳定的 e2e（attendance / pda / stockpile 等）**不标 smoke，继续 opt-in**，只在本地按需跑。

剥前缀反代（Caddy/nginx `handle_path /ui`）**不在本套范围**——harness 只验
"构建产物 + SPA fallback + 同源 Flask /api/*"，部署层剥前缀归部署 smoke。

## 设计要点

- **沙箱隔离**：session 级 fixture 在 tmp 目录建出 input/output/transfer/
  attendance/monthly_summary/archive/DB，再 monkeypatch 全局常量。生产数据
  不会被读写。
- **Flask 在 daemon 线程**：用 `werkzeug.serving.make_server`，端口 0 自动选；
  线程 daemon=True，进程退出自动收。
- **Console 错误监听**：`page_with_console` fixture 收集所有 `console.error`，
  每个 case 末尾 assert 列表为空。这是抓回归最大的杠杆。
- **通过 Alpine store 而非点击切换**：FAB / nav 走 `Alpine.store(...)` 改状态，
  避开点击坐标在不同 DPR 下漂移导致 flake。
- **认证 env 早于 create_app**：`FLASK_SECRET_KEY`/`UPLOAD_TOKEN` 在 `create_app()`
  前注入（`init_auth` 在内部 bake secret + seed admin，非 debug 缺 secret 会 fail-fast）；
  用 `create_app(seed_auth=True, prewarm=False)`。登录走浏览器 `page.request.post(/login)`，
  session cookie 落到 context，后续 `page.goto` 自带。
- **`/ui/*` 同源 serve**：harness 把 `frontend/dist` 挂到 `/ui/<path>`——实文件
  `send_from_directory`、无对应文件 fallback `index.html`（Vue history 路由）；`/api/*`
  仍由原 Flask 蓝图处理。nav 用例用 `Alpine.store('nav').pages` 运行时取存活集合（不硬编码），
  退役页自动跟随不漂移。

## 加新 case

只在以下情况下加：

- 发现一类必须在浏览器里才能验的回归（比如 JS 加载顺序、Alpine 时序、
  CSS 层叠 bug 等）
- 烟雾测试网格出现明显空白（比如某个新加的顶级 page）

不要把 e2e 当成 Playwright 单元测试库使。

### 反例：什么不该加

- ❌ store 状态变更（`Alpine.store('x').foo = 'bar'` → assert store 状态）—— 留给将来 Vitest，e2e 跑这个浪费 ~10s/case
- ❌ 后端 API 单测（建员工 / 改记录 → assert response）—— 已有 pytest 单测覆盖
- ❌ 业务逻辑分支（"如果 X 则 Y" 这类）—— 单测层

### 正例：哪些抓回归值

- ✅ Popover / drawer 的 **真 visibility**（不是 class includes，是 `wait_for(state="visible")`）
- ✅ Popover / 浮层的 **bbox 在 viewport 内**（positionPopover 越界 class 检查抓不到）
- ✅ 跨 CSS 文件的 **specificity 战争**（PR-FE-7b 那次：class 加了但被覆盖、视觉不更新）
- ✅ Alpine **init 时序**（store 初始化与 module script 执行的先后）

**断言形式**比"测什么"更重要——同一个 popover open，写成 class 检查会重蹈 PR-FE-7b 覆辙，
写成 `wait_for(visible)` + bbox 比较才真抓住"位置算错 / 被遮挡"这类只有浏览器能算的事。
