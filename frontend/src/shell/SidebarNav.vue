<script setup lang="ts">
import { computed } from "vue";
import { useCurrentUser } from "../stores/currentUser";
import { NAV_ITEMS, type NavItem } from "./nav-items";

const user = useCurrentUser();
const visible = computed(() => NAV_ITEMS.filter((i) => !i.requiresAdmin || user.isAdmin));
const modules = computed(() => visible.value.filter((i) => i.legacyPageId));
const primary = computed(() => visible.value.filter((i) => i.routeName)); // 简报等已迁

function legacyHref(i: NavItem): string {
  return `/?page=${i.legacyPageId}`;
}
</script>

<template>
  <nav class="sidebar-nav">
    <!-- 已迁页（简报）：RouterLink，置顶 -->
    <RouterLink
      v-for="i in primary"
      :key="i.id"
      class="nav-item"
      :class="{ active: $route.name === i.routeName }"
      :to="{ name: i.routeName }"
      :data-tooltip="i.label"
    >
      <span class="nav-icon"><svg viewBox="0 0 24 24"><use :href="`#icon-${i.icon}`" /></svg></span>
      <span class="nav-label">{{ i.label }}</span>
    </RouterLink>

    <div class="sidebar-section">MODULES · {{ modules.length }}</div>

    <!-- 未迁页：整页跳旧 SPA -->
    <a
      v-for="i in modules"
      :key="i.id"
      class="nav-item"
      :href="legacyHref(i)"
      :data-tooltip="i.label"
    >
      <span class="nav-icon"><svg viewBox="0 0 24 24"><use :href="`#icon-${i.icon}`" /></svg></span>
      <span class="nav-label">{{ i.label }}</span>
    </a>
  </nav>
</template>

<style scoped>
/* 从 static/css/components.css 移植 .sidebar-nav / .sidebar-section / .nav-item(.active) /
   .nav-icon / .nav-label 规则，全部用 token 变量，保持旧栈观感。 */
.sidebar-nav { display: flex; flex-direction: column; gap: var(--sp-1); padding: var(--sp-3) 0; overflow-y: auto; }
.sidebar-section { font-size: var(--fs-xs); color: var(--ink-2); text-transform: uppercase; letter-spacing: 0.05em; padding: var(--sp-3) var(--sp-4) var(--sp-2); }
.nav-item { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-2) var(--sp-4); color: var(--ink-1); text-decoration: none; background: none; border: 0; cursor: pointer; font-size: var(--fs-sm); border-left: 2px solid transparent; }
.nav-item:hover { background: var(--bg-2); color: var(--ink-0); }
.nav-item.active { color: var(--ink-0); border-left-color: var(--accent); background: var(--bg-2); }
.nav-icon { display: inline-flex; width: 18px; height: 18px; }
.nav-icon svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.nav-label { white-space: nowrap; }
</style>
