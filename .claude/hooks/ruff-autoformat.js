#!/usr/bin/env node
// 护栏⑤(ruff)：编辑 .py 后自动 `ruff format <file>`(纯排版, 安全), 再 `ruff check <file>` 只告警不改写。
//
// 全库已用钉死版本(0.15.12)规范化(chore/ruff-normalize), `ruff format <file>` 不再把单行编辑
// 炸成整文件 reformat, 自动改写价值回归。check 仍只提示不 --fix: per-edit 自动删导入(F401)
// 风险大(Flask 蓝图/ORM 有副作用导入), 留给模型/人工审。
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

  // ① 自动 format(改写文件, 纯排版安全)。ruff 缺失→静默跳过整个 hook。
  try {
    execFileSync(RUFF, ["format", fp], { stdio: ["ignore", "pipe", "pipe"] });
  } catch (e) {
    if (e && e.code === "ENOENT") process.exit(0);
    // format 失败(罕见: 语法错误等)→不阻塞, 继续走 check 提示
  }

  // ② check 只读告警, 不 --fix(per-edit 自动删导入风险大)。
  const notes = [];
  try {
    execFileSync(RUFF, ["check", fp], { stdio: ["ignore", "pipe", "pipe"] });
  } catch (e) {
    if (e && e.code === "ENOENT") process.exit(0);
    const out = `${(e && e.stdout) || ""}${(e && e.stderr) || ""}`.trim();
    if (out) notes.push(out);
  }

  if (notes.length) {
    const lines = notes.join("\n").split("\n").slice(0, MAX_NOTE_LINES);
    process.stderr.write(
      "ℹ️ ruff check 提示(已自动 format; 这些需手动审, 未 --fix):\n" + lines.join("\n") + "\n"
    );
  }
  process.exit(0);
});
