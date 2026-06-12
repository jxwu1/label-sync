<script setup lang="ts">
defineProps<{ title: string }>();
</script>

<template>
  <section class="card">
    <h3 class="card-title">{{ title }}</h3>
    <slot />
  </section>
</template>

<style scoped>
.card {
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: var(--sp-4);
}
.card-title {
  font-size: var(--fs-lg);
  margin: 0 0 var(--sp-3);
}
</style>
