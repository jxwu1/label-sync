<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string;
    value?: string;
    hint?: string;
    available?: boolean;
  }>(),
  { available: true, value: "", hint: "" },
);
</script>

<template>
  <div class="stat">
    <div class="stat__label">{{ label }}</div>
    <template v-if="available">
      <div class="stat__value">{{ value }}</div>
      <div v-if="hint" class="stat__hint">{{ hint }}</div>
    </template>
    <div v-else class="stat__na">暂不可用</div>
  </div>
</template>

<style scoped>
.stat {
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: var(--sp-4);
}
.stat__label {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--ink-2);
  margin-bottom: var(--sp-2);
}
.stat__value {
  font-family: var(--mono);
  font-size: var(--fs-2xl);
  color: var(--ink-0);
  line-height: 1.1;
}
.stat__hint {
  font-size: var(--fs-sm);
  color: var(--ink-1);
  margin-top: var(--sp-2);
}
.stat__na {
  font-size: var(--fs-sm);
  color: var(--ink-2);
}
</style>
