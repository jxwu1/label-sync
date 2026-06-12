import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
// 注意从 vitest/config 导入（配置里带 test 键，从 "vite" 导入会 TS 报错）
import { defineConfig } from "vitest/config";

// 跨 root 只精确放行 tokens 目录（绝对路径，避免 Windows/Linux 相对解析差异）
const tokensDir = fileURLToPath(new URL("../static/css", import.meta.url));
const frontendRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  base: "/ui/",
  plugins: [vue(), tailwindcss()],
  server: {
    fs: {
      // tokens 单源在仓库根 static/css/，跨 frontend root 读取（spec §7 v4）
      allow: [frontendRoot, tokensDir],
    },
    proxy: {
      "/api": { target: "http://127.0.0.1:5000", changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
  },
});
