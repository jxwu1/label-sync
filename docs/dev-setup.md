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
