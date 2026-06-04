#!/usr/bin/env node
// 护栏②：拦截会破坏 stockpile 主档 / 真数据的命令。
// 只拦真正危险的（rm -rf 真库/真数据目录、DROP/TRUNCATE/DELETE 主档表）。
// 不拦日常 alembic / wipe 派生数据。
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

  const danger = [
    /rm\s+-[a-z]*[rf][a-z]*\s+[^\n]*stockpile\.db/i, // 删主库文件
    /rm\s+-[a-z]*[rf][a-z]*\s+[^\n]*\/data(\/|\s|$)/i, // 删 /data 真数据目录
    /\b(DROP|TRUNCATE)\s+TABLE\s+["'`]?stockpile/i, // 删主档表
    /\bDELETE\s+FROM\s+["'`]?stockpile/i, // 清主档行
    /\b(DROP|TRUNCATE)\s+TABLE\s+["'`]?master_/i, // 删主档族表
  ];
  if (danger.some((re) => re.test(cmd))) {
    process.stderr.write(
      "⛔ 拦截：这条会破坏 stockpile 主档/真数据。确认无误请手动执行，不要在 auto mode 里跑。\n"
    );
    process.exit(2);
  }
  process.exit(0);
});
