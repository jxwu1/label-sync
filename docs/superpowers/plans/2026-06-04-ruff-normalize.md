# 全库 ruff 格式化基线规范化 Implementation Plan

> **For agentic workers:** 这是一次性工程治理（chore），非 feature。执行前确认活跃分支已清空（见 §前置）。

**Goal:** 用钉死的单一 ruff 版本把整库 Python 一次性规范化，消除"编辑旧文件→整文件 reformat"的 churn 历史债，之后把护栏⑤ ruff hook 从"只读告警"恢复为"自动格式化"。

**Architecture:** 版本三处对齐 → 分两段提交（先安全的 `format`，再需审查的 `check --fix`）→ 全量验证 → 合 main → 恢复 hook。

**背景：** 2026-06-04 试跑发现本地 ruff(0.15.13) 对既有代码大量报错（`ruff format .` 要动 73 文件、`ruff check .` 160 错）。短期已把 hook 改成只读告警止血（commit c6c5aa3）；本计划是长期治理终点。

---

## 前置条件（必须满足才开工）

- [ ] 活跃 feature 分支已合并/清空，避免 73 文件 commit 与其 rebase 大面积冲突。
      当前在飞：`feat+fetch-rows-dedup`(worktree)、`feat/fe-relayout`(未push)、`docs/skill-toolchain-design`。
      **这些先合掉再做本计划**，否则冲突地狱。
- [ ] 挑 Coolify 无后台长任务的时机（合 main 会触发 redeploy）。

---

## Task 1: 版本三处对齐

**Files:** `.pre-commit-config.yaml`、`requirements-dev.txt`、本地 `.venv`

选定版本 = **0.15.12**（与 pre-commit 当前 rev 一致）。用哪个版本规范化就把哪个钉死到所有三处，否则下个人的 ruff 又重排一轮。

- [ ] **Step 1: 确认 pin 一致**

```bash
grep -A1 "ruff-pre-commit" .pre-commit-config.yaml   # 应为 rev: v0.15.12
grep "^ruff==" requirements-dev.txt                  # 应为 ruff==0.15.12
```

- [ ] **Step 2: 把 venv 降到同版**

```bash
.venv/Scripts/python.exe -m pip install "ruff==0.15.12"
.venv/Scripts/python.exe -m ruff --version           # 应为 0.15.12
```

---

## Task 2: 开规范化分支

- [ ] **Step 1: 从最新 main 开 chore 分支**

```bash
git checkout main && git pull
git checkout -b chore/ruff-normalize
```

---

## Task 3: Commit 1 — `ruff format .`（纯排版, 安全）

`ruff format` 只动空白/换行/排版，**保证行为不变**。

- [ ] **Step 1: 跑 format**

```bash
.venv/Scripts/python.exe -m ruff format .
```

- [ ] **Step 2: 确认已规范**

```bash
.venv/Scripts/python.exe -m ruff format --check .    # 应输出 "N files already formatted"
```

- [ ] **Step 3: 全量测试（不可省, ~63s）**

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: 与基线一致（当前 980 passed, 3 既有 test_history_service 失败与本次无关）。

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "chore: ruff format 全库排版规范化(无业务改动)"
```

---

## Task 4: Commit 2 — `ruff check . --fix`（语义层, 需逐条审）

⚠️ **危险**：`--fix` 会动语义——删未用导入(F401)、重写语法(UP)、bugbear(B)。本项目 Flask 蓝图/ORM 很多 import **有副作用**（注册模型/路由），F401 删掉就崩。

- [ ] **Step 1: 先看会改什么（不落盘）**

```bash
.venv/Scripts/python.exe -m ruff check . --fix --diff > /tmp/ruff-fix.diff
```

- [ ] **Step 2: 逐条审 import 删除**：在 diff 里搜所有 `-import` / `-from`，确认被删的不是有副作用的注册型导入（models 注册、blueprint 注册、`# noqa: F401` 标记的 re-export）。对要保留的，加 `# noqa: F401` 而非删除。

- [ ] **Step 3: 应用 fix**

```bash
.venv/Scripts/python.exe -m ruff check . --fix
```

- [ ] **Step 4: 全量测试 + e2e 冒烟**

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/python.exe -m pytest e2e/ -q   # 浏览器冒烟(opt-in)
```
Expected: 仍与基线一致, 无新增失败。任何新失败 = `--fix` 改坏了行为, 回到 Step 2 审。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "chore: ruff check --fix 规范化(已审 import 删除, 无行为变化)"
```

---

## Task 5: 确认 CI-green 基线

- [ ] **Step 1: 照 CI 跑**

```bash
.venv/Scripts/python.exe -m ruff check .            # 0 errors
.venv/Scripts/python.exe -m ruff format --check .   # all formatted
```
Expected: 两条都干净（CI 的 ruff check . / ruff format --check . 会绿）。

---

## Task 6: 合 main（挑时机）

- [ ] 确认 Coolify 无后台长任务。
- [ ] squash/merge `chore/ruff-normalize` → main，push（触发 redeploy；纯格式化, 运行时行为不变）。

---

## Task 7: 恢复护栏⑤ hook 为"自动格式化 + lint 告警"

全库已规范化, `ruff format <file>` 不再大面积重排旧文件, 自动改写价值回归。

**Files:** `.claude/hooks/ruff-autoformat.js`、`tests/test_guard_hooks.py`

- [ ] **Step 1: 改 hook**：编辑 .py 后 **自动 `ruff format <file>`（纯排版, 安全）**；`ruff check <file>` **仍只告警不 `--fix`**（per-edit 自动删导入风险大）。仍用 venv ruff、非阻塞 exit 0。

- [ ] **Step 2: 改测试**：`test_ruff_hook_does_not_mutate_file` 改为验证"格式化会规范化该文件但不报错";新增"check 问题只告警不阻塞"。保持非阻塞 exit 0 契约。

```bash
python -m pytest tests/test_guard_hooks.py -q       # 全绿
```

- [ ] **Step 3: 提交**

```bash
git add .claude/hooks/ruff-autoformat.js tests/test_guard_hooks.py
git commit -m "feat(guard): 全库规范化后 ruff hook 恢复自动 format(check 仍只告警)"
```

---

## Self-Review

- **行为安全**：Task 3(format) 纯排版安全；Task 4(--fix) 靠 §Step2 审 import + 全量 pytest + e2e 兜底。
- **版本一致**：Task 1 三处对齐, 否则规范化白做。
- **冲突规避**：前置要求活跃分支先清空。
- **hook 终态**：format 自动 + check 告警, 兼顾价值与安全。
