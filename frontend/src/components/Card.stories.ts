import type { Meta, StoryObj } from "@storybook/vue3";
import Card from "./Card.vue";

const meta: Meta<typeof Card> = { component: Card, title: "基础/Card" };
export default meta;

export const Default: StoryObj<typeof Card> = {
  render: () => ({
    components: { Card },
    template: `<Card title="销售健康"><p>卡片内容</p></Card>`,
  }),
};
