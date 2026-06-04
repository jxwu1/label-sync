"""auto-mode 护栏 hook 行为测试。

每个 hook 是独立 Node 脚本，读 stdin JSON {tool_name, tool_input}，
exit 0 放行 / exit 2 拦截。这里用子进程喂合成 payload 验证拦放行为。
"""

import json
import os
import shutil
import subprocess
import pathlib

import pytest

HOOKS = pathlib.Path(__file__).resolve().parents[1] / ".claude" / "hooks"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="需要 node 运行 hook 脚本")


def _run(hook, *, command=None, file_path=None, tool_name="Bash", env=None):
    """跑一个 hook，返回 exit code。command 走 Bash payload，file_path 走 Edit payload。"""
    tool_input = {}
    if command is not None:
        tool_input["command"] = command
    if file_path is not None:
        tool_input["file_path"] = file_path
    payload = {"tool_name": tool_name, "tool_input": tool_input}
    p = subprocess.run(
        ["node", str(HOOKS / hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return p.returncode


# ── 护栏① block-push-main ────────────────────────────────────────────────
def _env_branch(name):
    return {**os.environ, "GIT_BRANCH_OVERRIDE": name}


def test_push_blocked_when_on_main():
    assert _run("block-push-main.js", command="git push", env=_env_branch("main")) == 2


def test_push_feat_branch_allowed():
    assert (
        _run("block-push-main.js", command="git push -u origin feat/x", env=_env_branch("feat/x"))
        == 0
    )


def test_explicit_push_to_main_blocked_from_feat():
    assert (
        _run("block-push-main.js", command="git push origin feat/x:main", env=_env_branch("feat/x"))
        == 2
    )


def test_non_push_git_allowed_on_main():
    assert _run("block-push-main.js", command="git status", env=_env_branch("main")) == 0


def test_main_word_in_later_segment_not_blocked():
    # "main" 仅出现在 push 之后的独立段（管道/echo），不应误拦（回归：扫整行的 bug）
    assert (
        _run(
            "block-push-main.js",
            command='git push origin feat/x | echo "deploy to main later"',
            env=_env_branch("feat/x"),
        )
        == 0
    )


# ── 护栏② guard-stockpile-destructive ────────────────────────────────────
def test_rm_rf_stockpile_blocked():
    assert _run("guard-stockpile-destructive.js", command="rm -rf /data/stockpile.db") == 2


def test_drop_master_table_blocked():
    assert _run("guard-stockpile-destructive.js", command='psql -c "DROP TABLE stockpile"') == 2


def test_delete_from_stockpile_blocked():
    assert (
        _run("guard-stockpile-destructive.js", command='psql -c "DELETE FROM stockpile WHERE 1=1"')
        == 2
    )


def test_alembic_upgrade_allowed_by_destructive_guard():
    assert _run("guard-stockpile-destructive.js", command="alembic upgrade head") == 0


def test_normal_rm_allowed():
    assert _run("guard-stockpile-destructive.js", command="rm -rf output/tmp") == 0


# ── 护栏③ migration-temp-db-guard ────────────────────────────────────────
def test_alembic_upgrade_without_temp_db_blocked():
    assert _run("migration-temp-db-guard.js", command="alembic upgrade head") == 2


def test_alembic_with_inline_sqlite_allowed():
    assert (
        _run(
            "migration-temp-db-guard.js",
            command="LABEL_SYNC_DB_PATH=/tmp/t.db alembic upgrade head",
        )
        == 0
    )


def test_alembic_history_allowed():
    assert _run("migration-temp-db-guard.js", command="alembic history") == 0


# ── 护栏④ env-file-guard ─────────────────────────────────────────────────
def test_edit_env_blocked():
    assert _run("env-file-guard.js", file_path="/c/Dev/label-sync/.env", tool_name="Edit") == 2


def test_edit_env_example_allowed():
    assert (
        _run("env-file-guard.js", file_path="/c/Dev/label-sync/.env.example", tool_name="Edit") == 0
    )


def test_edit_normal_py_allowed():
    assert (
        _run("env-file-guard.js", file_path="/c/Dev/label-sync/server.py", tool_name="Write") == 0
    )


# ── 护栏⑤ ruff-autoformat（PostToolUse，非阻塞，仅对 .py 动作）────────────
def test_ruff_hook_skips_non_py():
    # 非 .py 文件：直接放行 exit 0，不尝试 ruff
    assert _run("ruff-autoformat.js", file_path="static/js/app.js", tool_name="Edit") == 0


def test_ruff_hook_nonblocking_on_py():
    # .py 文件：即便 ruff 不在 PATH 也必须 exit 0（PostToolUse 非阻塞）
    assert _run("ruff-autoformat.js", file_path="server.py", tool_name="Edit") == 0


def test_ruff_hook_does_not_mutate_file(tmp_path):
    # 核心保证: hook 只读检查, 绝不改写文件(避免单行编辑炸成整文件 reformat 的 churn)
    bad = tmp_path / "bad.py"
    original = "import os,sys\nx=1\n"  # 故意格式不规范 + 未排序/未用导入
    bad.write_text(original, encoding="utf-8")
    _run("ruff-autoformat.js", file_path=str(bad), tool_name="Edit")
    assert bad.read_text(encoding="utf-8") == original
