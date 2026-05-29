# 开发环境 setup

新人/新机器 clone 仓库后第一次跑：

```bash
# Python 依赖
pip install -r requirements.txt
pip install ruff pre-commit

# 安装 git pre-commit 钩子
pre-commit install
```

完事。以后 `git commit` 会自动跑 ruff + ruff format。

---

## 本地开发循环（核心：改完本地即测，别上服务器调试）

线上跑的是 main，且 **push main 会自动触发 Coolify redeploy**。所以调试 **绝不** 在 main 上做——
每个 bug 在本地复现、修、验证，全过了再合并；服务器只接收已验证的代码。

一键起本地（本地 PG + 热重载）：

```powershell
./dev.ps1
```

它会：起本地 PostgreSQL 17（Docker，端口 5433）→ `alembic upgrade head` → 用 `LABEL_SYNC_DEBUG=1`
跑 `server.py`。**改 `.py` / `templates/*.html` 存盘即自动重载，不用手动重启 server。**

手动等价：

```powershell
docker compose -f docker-compose.dev.yml up -d
$env:DATABASE_URL = 'postgresql+psycopg://dev:devpass@localhost:5433/label_sync'
$env:LABEL_SYNC_DEBUG = '1'
python -m alembic upgrade head
python server.py
```

### 灌线上真实数据到本地（复现业务 bug 的前提）

空库跑标签流程出不了异常、复现不了业务 bug。把线上 PG 整库拉到本地一份：

```powershell
$env:PROD_DATABASE_URL = "postgresql://<user>:<pass>@<host>:<port>/<db>"  # 凭据在 1Password「Servers」vault
$env:DATABASE_URL      = "postgresql+psycopg://dev:devpass@localhost:5433/label_sync"
python tools/pull_prod_db.py
```

线上仅内网可达，外网跑需先开 SSH 隧道（脚本头部有说明）。只读线上、只覆盖本地，绝不反向写。

### 热重载的边界

- `LABEL_SYNC_DEBUG` **只本地设**。生产 Docker 不设 → `debug=False` → waitress 正常跑、模板照常缓存。
- `.py` 改动：werkzeug reloader 自动重启进程。
- `templates/*.html` 改动：Jinja `TEMPLATES_AUTO_RELOAD` 即时生效（debug 时自动开）。
- `static/*.css` / `*.js` 改动：本来就即时（静态文件每次新取），刷新浏览器即可。

## Claude Code 项目级 hook（可选，跨机器复现）

仓库内含一个项目级 post-commit hook（`.claude/hooks/gitnexus-post-commit.cjs`），
作用：每次 `.py` 改动 commit 后后台触发 `npx gitnexus analyze` 增量重索引。
配置已在 `.claude/settings.json` 入仓，**Claude Code 启动新 session 时会自动加载**。

CLAUDE.md 的「GitNexus 使用范围」覆盖段因为 skip-worktree 标志不入仓，需要手动追加：

```bash
# 新机器追加 CLAUDE.md 覆盖段（覆盖默认 "always do" 为 5 个具体场景）
cat .claude/CLAUDE.md.append >> CLAUDE.md
```

附加后，CLAUDE.md 末尾会多出「GitNexus 使用范围（本项目覆盖默认）」段，
narrowing 对 GitNexus 工具的强制使用范围。不做也行——只是更严格地遵守默认规则。

前端 JS lint 已移除（Phase 4，2026-05-16）；JS 代码靠 IDE 自带语法检查。

---

## 常用命令

```bash
# 手动跑全仓 lint（不必等 commit）
pre-commit run --all-files

# 仅 Python lint
python -m ruff check .

# 仅 Python lint + 自动修
python -m ruff check . --fix

# Python 格式化
python -m ruff format .

# 跑测试
python -m pytest -q
```

---

## alembic：不要默认打 prod

`alembic upgrade head` / `alembic revision --autogenerate` 默认连 `stockpile.db`（=prod）。
本地调试 / 测试期改用 `LABEL_SYNC_DB_PATH` 重定向到 tmp DB：

```bash
# Windows PowerShell
$env:LABEL_SYNC_DB_PATH=".test_tmp/dev.db"; alembic upgrade head

# bash
LABEL_SYNC_DB_PATH=.test_tmp/dev.db alembic upgrade head
```

未设环境变量时 fallback 到 `alembic.ini` 的默认 URL / `models.get_engine()`（即 prod）。

---

## lint 配置位置

- `pyproject.toml` → `[tool.ruff]` / `[tool.ruff.lint]` / `[tool.ruff.format]`
  - 启用规则：`E F I B UP`（pycodestyle / pyflakes / isort / bugbear / pyupgrade）
  - line-length: 100
- `.pre-commit-config.yaml` → 钩子组合（仅 ruff，Phase 4 已移除 eslint）

## Lint 规则放行说明

- `tests/*` 允许长行 (E501 off)
- `alembic/env.py` 允许长行 + 未用 import (模板生成代码)
- `archive/` / `.test_tmp/` / `alembic/versions/` 不参与 lint
- 以 `_` 开头的变量/参数不报"未用"

## 提交时绕过 lint（不推荐）

```bash
git commit --no-verify -m "..."
```

仅在 lint 误报或紧急修复时用。CLAUDE.md 准则：永远不在 AI 自动化中跳过 hook。

## warnings vs errors

- **errors**：阻塞 commit。当前规则集设计成 0 error
- **warnings**：commit 时显示但不阻塞，标志着"建议清理"
- 当前已知 warnings：无（Phase 4 移除 eslint 后只剩 ruff，规则集已 clean）

## 故障排查

**`pre-commit` 不存在或权限问题**：
```bash
pip install pre-commit && pre-commit install --overwrite
```

**ruff 跑出大量违规**：先 `--fix` + `format`，剩下的逐个看：
```bash
python -m ruff check . --fix
python -m ruff format .
python -m ruff check .  # 看剩余
```

**hook 在某个文件无限循环改格式**：删 `.git/hooks/pre-commit` 后排查；通常是 ruff 与编辑器自动格式化的双向冲突。
