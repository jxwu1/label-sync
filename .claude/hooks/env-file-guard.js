#!/usr/bin/env node
// 护栏④：拦截对 .env / 密钥文件的编辑（放行 .env.example 等模板）。
// 防 auto mode 误改注密钥的 .env。
// PreToolUse(Edit/Write)。exit 0 放行 / exit 2 拦截。
let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let fp = "";
  try {
    fp = (JSON.parse(raw).tool_input || {}).file_path || "";
  } catch {
    process.exit(0);
  }
  const base = fp.replace(/\\/g, "/").split("/").pop() || "";

  // 模板/示例放行
  if (/\.(example|sample|template|dist)$/i.test(base)) process.exit(0);

  // .env / .env.local / .env.production 等
  if (/^\.env(\..+)?$/i.test(base)) {
    process.stderr.write(
      "⛔ 拦截：禁止改 .env（含密钥）。要改密钥请手动操作或改 .env.example 模板。\n"
    );
    process.exit(2);
  }
  process.exit(0);
});
