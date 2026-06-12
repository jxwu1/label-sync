import type { Meta, StoryObj } from "@storybook/vue3";
import PageHeader from "./PageHeader.vue";

const meta: Meta<typeof PageHeader> = { component: PageHeader, title: "基础/PageHeader" };
export default meta;

export const WithSubtitle: StoryObj<typeof PageHeader> = {
  args: { title: "晨间简报", subtitle: "数据周 2026-06-08" },
};

export const TitleOnly: StoryObj<typeof PageHeader> = {
  args: { title: "晨间简报" },
};
