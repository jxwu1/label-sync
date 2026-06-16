/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
// 注意从 vitest/config 导入（配置里带 test 键，从 "vite" 导入会 TS 报错）
import { defineConfig } from "vitest/config";
import path from 'node:path';
import { storybookTest } from '@storybook/addon-vitest/vitest-plugin';
import { playwright } from '@vitest/browser-playwright';
import { fsAllow } from "./fs-allow";
const dirname = typeof __dirname !== 'undefined' ? __dirname : path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  base: "/ui/",
  plugins: [vue(), tailwindcss()],
  server: {
    fs: {
      // tokens 单源在仓库根 static/css/，跨 frontend root 读取（spec §7 v4）
      allow: fsAllow
    },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:5000",
        changeOrigin: false
      },
      // dev 跨栈：vite base 是 /ui/，自身 dev 资源全在 /ui/ 下；其余路径（旧 SPA 的
      // /?page=、/static、/login、各旧接口）一律转 Flask，让本地点未迁页也能真加载旧页、
      // 与生产同源行为一致。仅 dev server 生效，不影响 vite build 产物。
      "^(?!/ui/).+": {
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