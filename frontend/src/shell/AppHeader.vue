<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

const time = ref(new Date().toTimeString().slice(0, 8));
let timer: ReturnType<typeof setInterval> | undefined;

onMounted(() => {
  timer = setInterval(() => {
    time.value = new Date().toTimeString().slice(0, 8);
  }, 1000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <header class="header">
    <span class="header-clock">{{ time }}</span>
  </header>
</template>

<style scoped>
/* 从 static/css/components.css 移植 .header / .header-clock 规则，用 token。 */
.header { display: flex; align-items: center; justify-content: flex-end; height: 44px; padding: 0 var(--sp-5); border-bottom: 1px solid var(--line); }
.header-clock { font-family: var(--mono); font-size: var(--fs-sm); color: var(--ink-2); }
</style>
