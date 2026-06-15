import { createRouter, createWebHistory } from "vue-router";

export const router = createRouter({
  // base 单源 = vite base(/ui/); 写死字符串会与 vite.config 漂移
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: "/", redirect: "/briefing" },
    {
      path: "/briefing",
      component: () => import("./pages/briefing/BriefingPage.vue"),
    },
  ],
});
