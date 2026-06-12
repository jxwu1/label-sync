/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
// 注意从 vitest/config 导入（配置里带 test 键，从 "vite" 导入会 TS 报错）
import { defineConfig } from "vitest/config";

// 跨 root 只精确放行 tokens 目录（绝对路径，避免 Windows/Linux 相对解析差异）
import path from 'node:path';
import { storybookTest } from '@storybook/addon-vitest/vitest-plugin';
import { playwright } from '@vitest/browser-playwright';
const dirname = typeof __dirname !== 'undefined' ? __dirname : path.dirname(fileURLToPath(import.meta.url));

// More info at: https://storybook.js.org/docs/next/writing-tests/integrations/vitest-addon
const tokensDir = fileURLToPath(new URL("../static/css", import.meta.url));
const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
export default defineConfig({
  base: "/ui/",
  plugins: [vue(), tailwindcss()],
  server: {
    fs: {
      // tokens 单源在仓库根 static/css/，跨 frontend root 读取（spec §7 v4）
      allow: [frontendRoot, tokensDir]
    },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:5000",
        changeOrigin: false
      }
    }
  },
  test: {
    projects: [{
      extends: true,
      test: {
        name: "unit",
        environment: "jsdom"
      }
    }, {
      extends: true,
      plugins: [
      // The plugin will run tests for the stories defined in your Storybook config
      // See options at: https://storybook.js.org/docs/next/writing-tests/integrations/vitest-addon#storybooktest
      storybookTest({
        configDir: path.join(dirname, '.storybook')
      })],
      test: {
        name: 'storybook',
        browser: {
          enabled: true,
          headless: true,
          provider: playwright({}),
          instances: [{
            browser: 'chromium'
          }]
        }
      }
    }]
  }
});