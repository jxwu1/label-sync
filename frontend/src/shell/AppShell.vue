<script setup lang="ts">
import { onMounted } from "vue";
import { useCurrentUser } from "../stores/currentUser";
import AppHeader from "./AppHeader.vue";
import IconSprite from "./IconSprite.vue";
import SidebarNav from "./SidebarNav.vue";
import ThemeToggle from "./ThemeToggle.vue";

const user = useCurrentUser();
onMounted(() => {
  // 401 透传由 apiGet 接管跳登录；500 已在 store 内降级，不冒泡。
  user.load().catch(() => {});
});
</script>

<template>
  <div class="shell">
    <IconSprite />
    <aside class="sidebar">
      <div class="sidebar-head">
        <div class="sidebar-logo" aria-label="DataOps"><span>&gt;_</span></div>
        <div class="sidebar-brand">
          <div class="sidebar-brand-name">DataOps</div>
          <div class="sidebar-brand-sub">v4.8 · ADMIN</div>
        </div>
      </div>
      <SidebarNav />
      <div class="sidebar-foot">
        <a href="/logout" class="sidebar-foot-link">
          <span>⏻</span>
          <span class="sidebar-foot-label">{{ user.displayName ?? "—" }} · 登出</span>
        </a>
        <ThemeToggle />
      </div>
    </aside>
    <div class="main">
      <AppHeader />
      <RouterView />
    </div>
  </div>
</template>

<style scoped>
/* 从 static/css/components.css 移植 .shell / .sidebar / .sidebar-head / .sidebar-logo /
   .sidebar-brand* / .sidebar-foot* / .main 规则，用 token，保持旧栈观感。 */
.shell { display: flex; min-height: 100vh; background: var(--bg-0); }
.sidebar { display: flex; flex-direction: column; width: 220px; flex-shrink: 0; border-right: 1px solid var(--line); background: var(--bg-1); }
.sidebar-head { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-4); border-bottom: 1px solid var(--line); }
.sidebar-logo { font-family: var(--mono); color: var(--accent); font-weight: 600; }
.sidebar-brand-name { font-size: var(--fs-sm); color: var(--ink-0); font-weight: 600; }
.sidebar-brand-sub { font-size: var(--fs-xs); color: var(--ink-2); }
.sidebar-foot { margin-top: auto; padding: var(--sp-3) var(--sp-4); border-top: 1px solid var(--line); display: flex; flex-direction: column; gap: var(--sp-3); }
.sidebar-foot-link { display: flex; align-items: center; gap: var(--sp-2); color: var(--ink-1); text-decoration: none; font-size: var(--fs-sm); }
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
</style>
