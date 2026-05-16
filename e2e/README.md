# E2E 浏览器烟雾测试

只跑 5 个 case，抓"页面打不开 / 切 tab 报 console 错 / Alpine 初始化挂"这一类
**只有真浏览器才能发现**的回归。不写细粒度 UI 行为（roadmap 阶段 2 备忘已否过
Vitest store 单测；e2e 只看冒烟）。

## 一次性安装

```sh
pip install -r requirements-dev.txt
playwright install chromium
```

`playwright install` 会下载 ~150MB Chromium 到本地缓存（默认
`~/.cache/ms-playwright/`）。装完一次就好。

## 跑

```sh
pytest e2e/                  # 5 个 case
pytest e2e/ --headed         # 看着浏览器跑（调试用）
pytest e2e/ -k nav --headed  # 只看 nav 那批
```

## 默认不进 `pytest -q`

`e2e/` 没在 `pyproject.toml` 的 `testpaths` 里，所以日常 `pytest -q` 会跳过它，
不会变慢。要跑 e2e 必须显式 `pytest e2e/`。

## CI

不进 CI（按 roadmap 横切技术债同款定调，与 pre-commit 一致：本地闸门）。

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
