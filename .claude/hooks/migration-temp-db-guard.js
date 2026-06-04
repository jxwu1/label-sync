#!/usr/bin/env node
// 护栏③：alembic upgrade/downgrade 未指向临时 sqlite 时拦截。
// 防 auto mode 把迁移打到共享 PG 真库。
// PreToolUse(Bash)。exit 0 放行 / exit 2 拦截。
let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let cmd = "";
  try {
    cmd = (JSON.parse(raw).tool_input || {}).command || "";
  } catch {
    process.exit(0);
  }

  // 只管会改 schema 的迁移动作（history/current 等只读子命令放行）
  if (!/\balembic\s+(upgrade|downgrade)\b/.test(cmd)) process.exit(0);

  // 命令内联指定 LABEL_SYNC_DB_PATH 且指向 sqlite 文件 → 放行
  const m = cmd.match(/LABEL_SYNC_DB_PATH=([^\s]+)/);
  if (m && /\.db$|sqlite/i.test(m[1])) process.exit(0);

  process.stderr.write(
    "⛔ 拦截：迁移未指向临时 sqlite。用 `LABEL_SYNC_DB_PATH=/tmp/xxx.db alembic upgrade head` 验证，别打共享 PG 真库。\n"
  );
  process.exit(2);
});
