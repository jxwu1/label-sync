<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>();
</script>

<template>
  <header class="page-header">
    <h1 class="page-header__title">{{ title }}</h1>
    <p v-if="subtitle" class="page-header__subtitle">{{ subtitle }}</p>
  </header>
</template>

<style scoped>
.page-header {
  margin-bottom: var(--sp-6);
}
.page-header__title {
  font-size: var(--fs-2xl);
  font-weight: 600;
  color: var(--ink-0);
  margin: 0 0 var(--sp-1);
}
.page-header__subtitle {
  font-size: var(--fs-base);
  color: var(--ink-1);
  margin: 0;
}
</style>
