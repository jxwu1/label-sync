<script setup lang="ts">
import { ref } from "vue";

const current = ref(document.documentElement.dataset.theme === "light" ? "light" : "dark");

function set(theme: "dark" | "light") {
  current.value = theme;
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("theme", theme); // 仅浏览器本地（spec §8.3，不 PUT 服务端）
  } catch {
    /* ignore */
  }
}
</script>

<template>
  <div class="theme-switch">
    <button data-theme-btn="dark" :class="{ active: current === 'dark' }" @click="set('dark')">DARK</button>
    <button data-theme-btn="light" :class="{ active: current === 'light' }" @click="set('light')">LIGHT</button>
  </div>
</template>

<style scoped>
/* 从 static/css/components.css 移植 .theme-switch 规则，用 token。 */
.theme-switch { display: flex; gap: var(--sp-1); }
.theme-switch button { flex: 1; font-size: var(--fs-xs); padding: var(--sp-1) var(--sp-2); background: var(--bg-2); border: 1px solid var(--line); color: var(--ink-2); cursor: pointer; border-radius: var(--r-sm); }
.theme-switch button.active { color: var(--ink-0); border-color: var(--accent); }
</style>
