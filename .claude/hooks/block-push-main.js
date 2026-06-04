#!/usr/bin/env node
// 护栏①：拦截在 main 分支上的 git push，或显式 push 到 main。
// 防 Coolify 监听 main push → auto-redeploy 杀后台进程。
// PreToolUse(Bash)。exit 0 放行 / exit 2 拦截。
const { execFileSync } = require("child_process");

let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let cmd = "";
  try {
    cmd = (JSON.parse(raw).tool_input || {}).command || "";
  } catch {
    process.exit(0);
  }
  if (!/\bgit\s+push\b/.test(cmd)) process.exit(0);

  // 只取 git push 到下一个 shell 分隔符(| ; & 换行)之间的参数，
  // 避免误扫 echo/管道/后续命令里出现的 "main"。
  const pushArgs = (cmd.match(/\bgit\s+push\b([^\n|;&]*)/) || ["", ""])[1];
  // 显式推到 main：refspec 结尾 :main，或 main 作为独立分支参数。
  if (/:main\b/.test(pushArgs) || /(^|\s)main\b/.test(pushArgs)) {
    process.stderr.write(
      "⛔ 拦截：禁止 push 到 main（Coolify 会 auto-redeploy 杀后台进程）。走 feat 分支 + squash merge。\n"
    );
    process.exit(2);
  }

  // 当前分支是 main 时的任何 push
  let branch = process.env.GIT_BRANCH_OVERRIDE;
  if (!branch) {
    try {
      branch = execFileSync("git", ["rev-parse", "--abbrev-ref", "HEAD"], {
        encoding: "utf8",
      }).trim();
    } catch {
      branch = "";
    }
  }
  if (branch === "main") {
    process.stderr.write("⛔ 拦截：你在 main 上 push。先开 feat 分支。\n");
    process.exit(2);
  }
  process.exit(0);
});
