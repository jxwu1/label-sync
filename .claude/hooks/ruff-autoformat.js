#!/usr/bin/env node
// 护栏⑤(ruff 提示, 只读不改写)：编辑 .py 后用 ruff 检查该文件, 有问题打到 stderr 提示。
//
// 为何不自动 ruff format / --fix：本地 ruff 版本与项目基线漂移时, 改写会把一行编辑
// 炸成整文件 reformat 的 churn(实测 `ruff format .` 要动 73 文件)。改成只提示, 由模型
// 只修自己新增的行。待全库用钉死版本规范化后, 可再切回自动改写。
// 文件名保留(注册稳定)。PostToolUse(Edit/Write) 非阻塞：永远 exit 0。
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const MAX_NOTE_LINES = 12;

// 优先用项目 venv 的 ruff(钉死版本), 否则退回 PATH 上的 ruff。
function resolveRuff() {
  const root = process.env.CLAUDE_PROJECT_DIR || process.cwd();
  const candidates = [
    path.join(root, ".venv", "Scripts", "ruff.exe"), // Windows
    path.join(root, ".venv", "bin", "ruff"), // POSIX
  ];
  for (const c of candidates) {
    try {
      if (fs.existsSync(c)) return c;
    } catch {
      /* ignore */
    }
  }
  return "ruff"; // PATH 回退
}
const RUFF = resolveRuff();

let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let fp = "";
  try {
    fp = (JSON.parse(raw).tool_input || {}).file_path || "";
  } catch {
    process.exit(0);
  }
  if (!/\.py$/i.test(fp)) process.exit(0);

  const notes = [];
  for (const args of [
    ["check", fp],
    ["format", "--check", fp],
  ]) {
    try {
      // 退出 0 = 干净, 无输出
      execFileSync(RUFF, args, { stdio: ["ignore", "pipe", "pipe"] });
    } catch (e) {
      // ruff 缺失(ENOENT)→静默跳过; 非零退出(有问题)→收集输出做提示
      if (e && e.code === "ENOENT") process.exit(0);
      const out = `${(e && e.stdout) || ""}${(e && e.stderr) || ""}`.trim();
      if (out) notes.push(out);
    }
  }

  if (notes.length) {
    const lines = notes.join("\n").split("\n").slice(0, MAX_NOTE_LINES);
    process.stderr.write(
      "ℹ️ ruff 提示(未自动改, 只修你本次新增的行即可):\n" + lines.join("\n") + "\n"
    );
  }
  process.exit(0);
});
