import type { StorybookConfig } from "@storybook/vue3-vite";
import { fsAllow } from "../fs-allow.js";

const config: StorybookConfig = {
  framework: "@storybook/vue3-vite",
  stories: ["../src/**/*.stories.ts"],
  addons: [
    "@chromatic-com/storybook",
    "@storybook/addon-vitest",
    "@storybook/addon-a11y",
    "@storybook/addon-docs",
    "@storybook/addon-onboarding",
  ],
  async viteFinal(cfg) {
    // Storybook 的 Vite builder 不继承 vite.config.ts 的 server.fs.allow —
    // 跨 root 读 ../static/css/tokens.css 必须在此重复放行（spec 四轮 review）
    cfg.server = cfg.server ?? {};
    cfg.server.fs = {
      ...cfg.server.fs,
      allow: fsAllow,
    };
    return cfg;
  },
};
export default config;
