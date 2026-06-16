import { createRouter, createWebHistory } from "vue-router";
import AppShell from "./shell/AppShell.vue";

export const router = createRouter({
  // base 单源 = vite base(/ui/); 写死字符串会与 vite.config 漂移
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/",
      component: AppShell,
      children: [
        { path: "", redirect: { name: "briefing" } },
        { path: "briefing", name: "briefing", component: () => import("./pages/briefing/BriefingPage.vue") },
      ],
    },
  ],
});
