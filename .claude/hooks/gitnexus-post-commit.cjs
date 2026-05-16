#!/usr/bin/env node
/**
 * Project-level GitNexus post-commit hook for label-sync.
 *
 * Hook event: PostToolUse on Bash
 *
 * Behaviour: when a `git commit` Bash call succeeds AND the commit touched
 * any .py file, spawn `npx gitnexus analyze` in the background. `analyze`
 * has built-in HEAD-vs-last-indexed gating, so a no-op commit (or re-trigger
 * while a previous run is still in flight) is cheap.
 *
 * Also opportunistically warns when the current session never called
 * `mcp__gitnexus__detect_changes` before committing .py changes. The warning
 * is informational — does not block the commit.
 *
 * Stays silent (exits 0 with no stdout) for any Bash that is not a successful
 * `git commit`, so it does not pollute unrelated tool output.
 */

const fs = require('fs');
const { spawn, spawnSync } = require('child_process');

function readInput() {
  try {
    return JSON.parse(fs.readFileSync(0, 'utf-8'));
  } catch {
    return {};
  }
}

function emit(message) {
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PostToolUse',
        additionalContext: message,
      },
    }),
  );
}

function isSuccessfulGitCommit(input) {
  if (input.tool_name !== 'Bash') return false;
  const cmd = input.tool_input?.command || '';
  if (!/\bgit\s+commit\b/.test(cmd)) return false;
  if (/--amend/.test(cmd)) return false;
  const exit =
    input.tool_response?.exit_code ?? input.tool_response?.exitCode ?? null;
  return exit === 0;
}

function commitTouchedPython(cwd) {
  // Windows: spawnSync needs shell:true to resolve `git` from PATH.
  const r = spawnSync('git', ['diff', '--name-only', 'HEAD~1', 'HEAD'], {
    cwd,
    encoding: 'utf-8',
    shell: true,
    windowsHide: true,
  });
  if (r.status !== 0) return false;
  return (r.stdout || '')
    .split(/\r?\n/)
    .filter(Boolean)
    .some((f) => f.endsWith('.py'));
}

function sessionCalledDetectChanges(transcriptPath) {
  try {
    if (!transcriptPath || !fs.existsSync(transcriptPath)) return null;
    const text = fs.readFileSync(transcriptPath, 'utf-8');
    return /mcp__gitnexus__detect_changes/.test(text);
  } catch {
    return null;
  }
}

function spawnAnalyzeDetached(cwd) {
  try {
    const child = spawn('npx', ['gitnexus', 'analyze'], {
      cwd,
      detached: true,
      stdio: 'ignore',
      shell: true,
      windowsHide: true,
    });
    child.unref();
    return true;
  } catch {
    return false;
  }
}

function main() {
  const input = readInput();
  if (!isSuccessfulGitCommit(input)) return;

  const cwd = input.cwd || process.cwd();
  if (!commitTouchedPython(cwd)) return;

  const ok = spawnAnalyzeDetached(cwd);
  let msg = ok
    ? '[GitNexus] 检测到 .py 改动 commit，已后台触发 `npx gitnexus analyze`（HEAD 已索引时自动 no-op）。'
    : '[GitNexus] 想后台跑 `npx gitnexus analyze` 但 spawn 失败，请手动跑一次。';

  const called = sessionCalledDetectChanges(input.transcript_path);
  if (called === false) {
    msg +=
      '\n[GitNexus warn] 本次 session 未调用 mcp__gitnexus__detect_changes —— commit 已落，下次记得 commit 前先验证影响范围。';
  }

  emit(msg);
}

try {
  main();
} catch (err) {
  if (process.env.GITNEXUS_DEBUG) {
    console.error('gitnexus-post-commit hook error:', err.message);
  }
}
