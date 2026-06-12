import type { Meta, StoryObj } from "@storybook/vue3";
import Badge from "./Badge.vue";

const meta: Meta<typeof Badge> = { component: Badge, title: "基础/Badge" };
export default meta;

export const FourTones: StoryObj<typeof Badge> = {
  render: () => ({
    components: { Badge },
    template: `
      <div style="display:flex;gap:8px">
        <Badge tone="ok">正常</Badge>
        <Badge tone="warn">注意</Badge>
        <Badge tone="danger">异常</Badge>
        <Badge tone="muted">无数据</Badge>
      </div>`,
  }),
};
