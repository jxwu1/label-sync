# Skill 工具链迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ECC 臃肿插件换成"Addy 脊柱 + superpowers 动力 + 4 个 cherry-pick skill + 3 条护栏 hook"的固定工具链，且 auto mode 有硬护栏。

**Architecture:** 先加法（装 Addy/Anthropic 插件、拷 4 个 ECC skill 成独立全局 skill、写 3 条 PreToolUse hook）→ 试运行 → 最后不可逆减法（卸 ECC）。hook 用 Node 写、pytest 子进程测试。

**Tech Stack:** Claude Code plugins (`/plugin`)、`~/.claude/skills/`、Claude Code PreToolUse hooks (Node.js)、pytest subprocess。

**设计来源：** `docs/superpowers/specs/2026-06-04-skill-toolchain-design.md`

**对 spec 的修正（执行中发现）：**
1. html-mirror 是项目级 skill（`.claude/skills/html-mirror`），不属于 ECC，卸 ECC 不影响它 → 无需 cherry-pick。
2. **deep-research 只存在于 ECC** → 必须 cherry-pick，加入清单（共 5 个 skill）。
3. **exa-search 和 context7 是 ECC 提供的 MCP 服务** → 卸 ECC 会端掉它们，必须独立重装（新增 Task A4）。
   - context7：`npx -y @upstash/context7-mcp@2.1.4`（无需 key）
   - exa：HTTP MCP `https://mcp.exa.ai/mcp`（无需 key）

---

## 执行进度（2026-06-04）

- ✅ **Phase A 加法**：4 skill cherry-pick（accessibility/eval-harness/mle-workflow/inventory-demand-planning）；Addy + Claude Code Setup 装好；context7 + exa 独立 MCP（**user 级**）。拷错的 firecrawl 版 deep-research 已删，搜索深度研究用独立的 fan-out 版。
- ✅ **Phase B 推荐**：Claude Code Setup 跑过，采纳额外 2 条 hook（ruff 自动格式化 + .env 拦截）。
- ✅ **Phase C 护栏**：**5 条** hook 全部 TDD 实现、注册、18 用例全绿、已提交。比原计划多 2 条（C4 ruff-autoformat / C5 env-file-guard）。实测抓到并修复了 block-push-main 误扫整行的 false-positive。
- 🔄 **Phase D 试运行（进行中）**：拿"`/sku` 取数去重 3→1"试跑了完整脊柱（/spec→worktree→TDD→pytest→fresh-subagent 审→Codex），功能落在 worktree `feat+fetch-rows-dedup`（未 merge）。
  - **试跑修正**：护栏⑤ ruff hook 原为自动 `ruff format`，实测会把一行编辑炸成整文件 reformat 的 churn（本地 ruff 对既有代码大量误报）→ 已改为**只读告警、不改写**，优先用 venv ruff，并在 requirements-dev 钉 `ruff==0.15.12`。
  - **未做的后续选项**：若想恢复"自动改写"，需先用钉死的 ruff 全库规范化一次（`ruff format . && ruff check --fix .`，约 73 文件）作为单独一期，之后 auto-format 才不 churn。
- ⏳ **Phase E 卸 ECC（不可逆，待 fan-out deep-research 存活验证）**。

## 文件结构

| 文件 | 责任 |
|---|---|
| `~/.claude/skills/{accessibility,eval-harness,mle-workflow,inventory-demand-planning}/` | 从 ECC 拷出的独立全局 skill |
| `.claude/hooks/block-push-main.js` | 护栏①：在 main 上 git push 时拦截 |
| `.claude/hooks/guard-stockpile-destructive.js` | 护栏②：rm -rf 真数据 / 删主档 SQL 时拦截 |
| `.claude/hooks/migration-temp-db-guard.js` | 护栏③：alembic 迁移未指向临时库时拦截 |
| `.claude/settings.json` | 注册上面 3 条 PreToolUse hook |
| `tests/test_guard_hooks.py` | 3 条 hook 的拦/放行行为测试（pytest 子进程喂 JSON） |

护栏 hook 放**项目级** `.claude/`（只在 label-sync 生效，引用 stockpile/Coolify 等本项目语义）。

---

## Phase A — 加法（零风险，可回退）

### Task A1: cherry-pick 4 个 ECC skill 成独立全局 skill

**Files:**
- Create: `~/.claude/skills/accessibility/` 等 4 个目录（从 ECC 缓存拷贝）

来源根：`C:/Users/64474/.claude/plugins/cache/ecc/ecc/2.0.0-rc.1/skills/`

- [x] **Step 1: 拷贝 5 个 skill 目录**（含 deep-research）

```bash
SRC="C:/Users/64474/.claude/plugins/cache/ecc/ecc/2.0.0-rc.1/skills"
DST="C:/Users/64474/.claude/skills"
mkdir -p "$DST"
for s in accessibility eval-harness mle-workflow inventory-demand-planning deep-research; do
  cp -r "$SRC/$s" "$DST/$s"
done
```

- [x] **Step 2: 验证 5 个都到位且有 SKILL.md**（2026-06-04 已执行，全 OK）

```bash
for s in accessibility eval-harness mle-workflow inventory-demand-planning deep-research; do
  test -f "C:/Users/64474/.claude/skills/$s/SKILL.md" && echo "OK $s" || echo "MISS $s"
done
```
Expected: 5 行全 `OK`

- [ ] **Step 3: 验证 frontmatter 的 name 字段无 `ecc:` 前缀残留**（独立 skill 不应带命名空间）

```bash
grep -h "^name:" "C:/Users/64474/.claude/skills"/{accessibility,eval-harness,mle-workflow,inventory-demand-planning}/SKILL.md
```
Expected: 4 个 name，若带 `ecc:` 前缀则手动去掉前缀

- [ ] **Step 4: 提交**（这些是用户级 skill，不在项目 repo；本步仅记录，无 git）

无需 commit（`~/.claude/skills/` 不在 label-sync repo）。

---

### Task A2: 安装 Addy agent-skills（**用户操作**）

- [ ] **Step 1: 用户在 Claude Code 敲**

```
/plugin marketplace add addyosmani/agent-skills
/plugin install agent-skills@addy-agent-skills
```

- [ ] **Step 2: 验证 7 个 slash 命令出现**

在 Claude Code 输入 `/` 看是否有 `/spec /plan /build /test /review /code-simplify /ship`。
Expected: 7 个命令可见。

---

### Task A3: 安装 Anthropic Claude Code Setup（**用户操作**）

- [ ] **Step 1: 用户敲 `/plugin`** → 找 **Claude Code Setup**（Anthropic, verified）→ install
- [ ] **Step 2: 验证** `/plugin` 列表里出现 Claude Code Setup（enabled）

---

### Task A4: 独立重装 exa + context7 MCP（保住搜索层，卸 ECC 前必须）

> 背景：exa 和 context7 原本是 ECC 插件提供的 MCP，卸 ECC 会一并端掉。独立装回来，均无需 API key。

- [ ] **Step 1: 加 context7（npx 本地 MCP）**

```bash
claude mcp add context7 -- npx -y @upstash/context7-mcp@2.1.4
```

- [ ] **Step 2: 加 exa（HTTP 远程 MCP）**

```bash
claude mcp add --transport http exa https://mcp.exa.ai/mcp
```

- [ ] **Step 3: 验证两个 MCP 在线**

```bash
claude mcp list
```
Expected: 列表含 `context7` 和 `exa`，状态 connected。

注：这两条独立 MCP 与 ECC 的同名 MCP 会临时并存（Phase E 卸 ECC 后只剩独立的）。若 server 名冲突，独立的用 `context7-std` / `exa-std` 命名。

---

## Phase B — 拿推荐

### Task B1: 跑 Anthropic Setup 推荐，沉淀建议

- [ ] **Step 1: 用户在 label-sync 里说** "recommend automations for this project"
- [ ] **Step 2: 把它给的 hook/MCP/skill 建议贴回会话**，Claude 比对设计，决定哪些 hook 建议并入 Phase C（值得的补，重复的跳过）

---

## Phase C — 护栏 hook（代码，TDD）

> Claude Code PreToolUse hook 协议：stdin 收到 JSON `{tool_name, tool_input:{command}}`；**exit 0 放行，exit 2 拦截**（stderr 文案回给模型/用户）。

### Task C0: 建 hooks 目录 + 读现有 settings

- [ ] **Step 1: 建目录 + 看现有 settings.json**

```bash
mkdir -p "C:/Dev/label-sync/.claude/hooks"
cat "C:/Dev/label-sync/.claude/settings.json" 2>/dev/null || echo "{}"
```
记录现有 `hooks` 结构，Task C4 合并时不覆盖。

---

### Task C1: 护栏① 禁止在 main 上 push

**Files:**
- Create: `.claude/hooks/block-push-main.js`
- Test: `tests/test_guard_hooks.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_guard_hooks.py
import json, subprocess, pathlib, os
HOOKS = pathlib.Path(__file__).resolve().parents[1] / ".claude" / "hooks"

def _run(hook, command, env=None):
    p = subprocess.run(
        ["node", str(HOOKS / hook)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
        capture_output=True, text=True, env=env,
    )
    return p.returncode

def test_push_main_blocked_when_on_main():
    env = {**os.environ, "GIT_BRANCH_OVERRIDE": "main"}
    assert _run("block-push-main.js", "git push", env=env) == 2

def test_push_feat_branch_allowed():
    env = {**os.environ, "GIT_BRANCH_OVERRIDE": "feat/x"}
    assert _run("block-push-main.js", "git push -u origin feat/x", env=env) == 0

def test_explicit_push_to_main_blocked():
    env = {**os.environ, "GIT_BRANCH_OVERRIDE": "feat/x"}
    assert _run("block-push-main.js", "git push origin feat/x:main", env=env) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_guard_hooks.py -k push -v`
Expected: FAIL（hook 文件不存在 → node 报错）

- [ ] **Step 3: 写 hook**

```javascript
// .claude/hooks/block-push-main.js
const { execSync } = require("child_process");
let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let cmd = "";
  try { cmd = (JSON.parse(raw).tool_input || {}).command || ""; } catch {}
  if (!/\bgit\s+push\b/.test(cmd)) process.exit(0);

  // 显式推到 main（如 feat:main、origin main、HEAD:main）
  if (/[:\s]main\b/.test(cmd.replace(/\bgit\s+push\b/, ""))) {
    process.stderr.write("⛔ 拦截：禁止 push 到 main（Coolify 会 auto-redeploy 杀后台进程）。走 feat 分支 + squash merge。\n");
    process.exit(2);
  }
  // 当前分支是 main 时的任何 push
  let branch = process.env.GIT_BRANCH_OVERRIDE;
  if (!branch) {
    try { branch = execSync("git rev-parse --abbrev-ref HEAD", { encoding: "utf8" }).trim(); } catch { branch = ""; }
  }
  if (branch === "main") {
    process.stderr.write("⛔ 拦截：你在 main 上 push。先开 feat 分支。\n");
    process.exit(2);
  }
  process.exit(0);
});
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_guard_hooks.py -k push -v`
Expected: 3 个 push 测试 PASS

- [ ] **Step 5: 提交**

```bash
git add .claude/hooks/block-push-main.js tests/test_guard_hooks.py
git commit -m "feat(guard): hook 拦截 main 分支 push"
```

---

### Task C2: 护栏② 主档破坏性操作拦截

**Files:**
- Create: `.claude/hooks/guard-stockpile-destructive.js`
- Modify: `tests/test_guard_hooks.py`

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 tests/test_guard_hooks.py

def test_rm_rf_stockpile_blocked():
    assert _run("guard-stockpile-destructive.js", "rm -rf /data/stockpile.db") == 2

def test_drop_master_table_blocked():
    assert _run("guard-stockpile-destructive.js", 'psql -c "DROP TABLE stockpile"') == 2

def test_alembic_upgrade_allowed():
    # 日常迁移派生数据不该被这条拦
    assert _run("guard-stockpile-destructive.js", "alembic upgrade head") == 0

def test_normal_rm_allowed():
    assert _run("guard-stockpile-destructive.js", "rm -rf output/tmp") == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_guard_hooks.py -k "stockpile or master or alembic_upgrade_allowed or normal_rm" -v`
Expected: FAIL（文件不存在）

- [ ] **Step 3: 写 hook**

```javascript
// .claude/hooks/guard-stockpile-destructive.js
let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let cmd = "";
  try { cmd = (JSON.parse(raw).tool_input || {}).command || ""; } catch {}

  const danger = [
    /rm\s+-[rf]+\s+[^\n]*stockpile\.db/i,             // 删主库文件
    /rm\s+-[rf]+\s+[^\n]*\/data(\/|\s|$)/i,           // 删 /data 真数据目录
    /\b(DROP|TRUNCATE)\s+TABLE\s+["'`]?stockpile/i,   // 删主档表
    /\bDELETE\s+FROM\s+["'`]?stockpile/i,             // 清主档行
    /\b(DROP|TRUNCATE)\s+TABLE\s+["'`]?master_/i,     // 删主档族表
  ];
  if (danger.some((re) => re.test(cmd))) {
    process.stderr.write("⛔ 拦截：这条会破坏 stockpile 主档/真数据。确认无误请手动执行，不要在 auto mode 里跑。\n");
    process.exit(2);
  }
  process.exit(0);
});
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_guard_hooks.py -k "stockpile or master or alembic_upgrade_allowed or normal_rm" -v`
Expected: 4 个 PASS

- [ ] **Step 5: 提交**

```bash
git add .claude/hooks/guard-stockpile-destructive.js tests/test_guard_hooks.py
git commit -m "feat(guard): hook 拦截主档破坏性操作"
```

---

### Task C3: 护栏③ 迁移强制临时库

**Files:**
- Create: `.claude/hooks/migration-temp-db-guard.js`
- Modify: `tests/test_guard_hooks.py`

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 tests/test_guard_hooks.py

def test_alembic_upgrade_without_temp_db_blocked():
    assert _run("migration-temp-db-guard.js", "alembic upgrade head") == 2

def test_alembic_with_inline_sqlite_allowed():
    assert _run("migration-temp-db-guard.js",
        "LABEL_SYNC_DB_PATH=/tmp/t.db alembic upgrade head") == 0

def test_non_migration_allowed():
    assert _run("migration-temp-db-guard.js", "alembic history") == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_guard_hooks.py -k "alembic_upgrade_without or inline_sqlite or non_migration" -v`
Expected: FAIL

- [ ] **Step 3: 写 hook**

```javascript
// .claude/hooks/migration-temp-db-guard.js
let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let cmd = "";
  try { cmd = (JSON.parse(raw).tool_input || {}).command || ""; } catch {}

  // 只管会改 schema 的迁移动作
  if (!/\balembic\s+(upgrade|downgrade)\b/.test(cmd)) process.exit(0);

  // 命令内联指定了 LABEL_SYNC_DB_PATH 且指向 sqlite 文件 → 放行
  const m = cmd.match(/LABEL_SYNC_DB_PATH=([^\s]+)/);
  if (m && /\.db$|sqlite/i.test(m[1])) process.exit(0);

  process.stderr.write("⛔ 拦截：迁移未指向临时 sqlite。用 `LABEL_SYNC_DB_PATH=/tmp/xxx.db alembic upgrade head` 验证，别打共享 PG 真库。\n");
  process.exit(2);
});
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_guard_hooks.py -k "alembic_upgrade_without or inline_sqlite or non_migration" -v`
Expected: 3 个 PASS

- [ ] **Step 5: 提交**

```bash
git add .claude/hooks/migration-temp-db-guard.js tests/test_guard_hooks.py
git commit -m "feat(guard): hook 强制迁移走临时库"
```

---

### Task C4: 注册 3 条 hook 到 settings.json

**Files:**
- Modify: `.claude/settings.json`

- [ ] **Step 1: 合并 PreToolUse hook**（读现有 settings，把下面 3 条加进 `hooks.PreToolUse`，matcher 限 Bash；不覆盖已有项）

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/hooks/block-push-main.js\"" },
          { "type": "command", "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/hooks/guard-stockpile-destructive.js\"" },
          { "type": "command", "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/hooks/migration-temp-db-guard.js\"" }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: 全量跑 hook 测试**

Run: `pytest tests/test_guard_hooks.py -v`
Expected: 全 PASS（约 10 个 case）

- [ ] **Step 3: 实测拦截生效**（用 `GIT_BRANCH_OVERRIDE=main` 跑一次 node hook 看 exit 2）

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"git push"}}' | GIT_BRANCH_OVERRIDE=main node .claude/hooks/block-push-main.js; echo "exit=$?"
```
Expected: `exit=2`

- [ ] **Step 4: 提交**

```bash
git add .claude/settings.json
git commit -m "feat(guard): 注册 3 条护栏 hook 到 PreToolUse"
```

---

## Phase D — 试运行（人工，2 天）

### Task D1: 真实任务里跑新工作流

- [ ] 用新脊柱跑一个真任务（如老板 backlog #2 或 sku_summary 物化）：`/spec`→`/plan`→worktree→`/build`(TDD)→`/test`→subagent review→Codex review→`/ship`
- [ ] 确认 hook 不误拦日常操作（feat 分支 push、派生数据 wipe、临时库迁移都放行）
- [ ] 记录摩擦点

---

## Phase E — 减法（不可逆，**执行前再次确认**）

### Task E1: 卸载 ECC（**用户操作 + 卸载前复核**）

- [ ] **Step 1: 复核 4 个 cherry-pick skill 已独立可用**

```bash
for s in accessibility eval-harness mle-workflow inventory-demand-planning; do
  test -f "C:/Users/64474/.claude/skills/$s/SKILL.md" && echo "OK $s" || echo "MISS $s"
done
```
Expected: 4 个 OK（否则**停**，别卸 ECC）

- [ ] **Step 2: 用户卸载 ECC** `/plugin` → 找 ecc → uninstall（或 `/plugin uninstall ecc`）

- [ ] **Step 3: 验证善后**
  - `/` 列表里 `ecc:*` skill 全消失
  - GateGuard 不再触发（bash/write 不再要"陈述事实"）
  - `dailybrief-hook.ps1` 仍在 settings.json（个人脚本未受影响）
  - Addy 的 `/spec` 等仍在、4 个 cherry-pick skill 仍可用、html-mirror 仍在

---

### Task E2: 记录到 memory

- [ ] 写 `project_skill_toolchain_frozen.md`（type: project）：冻结的三层工具链、cherry-pick 的 4 skill、3 条 hook、ECC 已卸；更新 `MEMORY.md` 索引
- [ ] 关联 `[[feedback_git_workflow_branches]] [[feedback_no_main_push_during_long_job]] [[project_thesis_rewrite_plan]]`

---

## Self-Review

- **Spec 覆盖**：层①(Addy+superpowers=A2/D1)、层②(3 hook=C1/C2/C3/C4)、层③(预测/搜索 skill=A1 拷 + A2 装 Addy 带的)、安装/卸载清单(A2/A3/E1)、先加后减(Phase 顺序) — 均有任务。论文=无 → 无任务（正确）。
- **占位符**：无 TBD；hook 代码与测试均完整。
- **类型一致**：测试辅助 `_run(hook, command, env=None)` 在 C1 定义、C2/C3 复用，签名一致。

**未决项（执行时确认）：**
- `deep-research`/`exa-search`/`context7` 来源：deep-research 可能来自 superpowers 或 ECC；exa/context7 是 MCP（已在 deferred 工具里）。执行 A1 前确认 deep-research 若来自 ECC 则一并 cherry-pick（加进 Task A1 列表）。
- Anthropic 插件推荐的 hook（Phase B）可能要求新增 Task C5+。
