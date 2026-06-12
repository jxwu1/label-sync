import { createRouter, createWebHistory } from "vue-router";

export const router = createRouter({
  history: createWebHistory("/ui/"),
  routes: [
    { path: "/", redirect: "/briefing" },
    {
      path: "/briefing",
      component: () => import("./pages/briefing/BriefingPage.vue"),
    },
  ],
});
