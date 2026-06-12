import type { Meta, StoryObj } from "@storybook/vue3";

const meta: Meta = { title: "规范/Tokens" };
export default meta;

const SPACINGS = ["--sp-1", "--sp-2", "--sp-3", "--sp-4", "--sp-5", "--sp-6", "--sp-7", "--sp-8"];
const FONTS = ["--fs-xs", "--fs-sm", "--fs-md", "--fs-base", "--fs-lg", "--fs-xl", "--fs-2xl"];
const COLORS = [
  { name: "--success", label: "success" },
  { name: "--warn", label: "warn" },
  { name: "--error", label: "error" },
  { name: "--info", label: "info" },
  { name: "--accent", label: "accent" },
];

export const SpacingAndFontSize: StoryObj = {
  render: () => ({
    setup: () => ({ SPACINGS, FONTS }),
    template: `
      <div>
        <h3>spacing（8pt grid）</h3>
        <div v-for="v in SPACINGS" :key="v" style="display:flex;gap:8px;align-items:center;margin-bottom:4px">
          <code style="width:80px">{{ v }}</code>
          <div :style="{ width: 'var(' + v + ')', height: '12px', background: 'currentColor' }" />
        </div>
        <h3>font sizes</h3>
        <p v-for="v in FONTS" :key="v" :style="{ fontSize: 'var(' + v + ')' }">{{ v }} — 简报示例文字</p>
      </div>`,
  }),
};

export const SemanticColors: StoryObj = {
  render: () => ({
    setup: () => ({ COLORS }),
    template: `
      <div>
        <h3>语义色（需 data-theme 上下文）</h3>
        <div v-for="c in COLORS" :key="c.name" style="display:flex;gap:12px;align-items:center;margin-bottom:8px">
          <div :style="{ width: '32px', height: '32px', borderRadius: '4px', background: 'var(' + c.name + ')' }" />
          <code>{{ c.name }}</code>
          <span>{{ c.label }}</span>
        </div>
      </div>`,
  }),
};
