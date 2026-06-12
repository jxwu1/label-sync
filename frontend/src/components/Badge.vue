<script setup lang="ts">
withDefaults(defineProps<{ tone?: "ok" | "warn" | "danger" | "muted" }>(), {
  tone: "muted",
});
</script>

<template>
  <span :class="['badge', `badge--${tone}`]"><slot /></span>
</template>

<style scoped>
.badge {
  display: inline-block;
  font-size: var(--fs-sm);
  font-weight: 500;
  padding: var(--sp-1) var(--sp-2);
  border-radius: var(--r-pill);
  line-height: 1;
}
.badge--ok {
  color: var(--success);
  background: var(--success-subtle);
}
.badge--warn {
  color: var(--warn-dim);
  background: var(--warn-subtle);
}
.badge--danger {
  color: var(--error);
  background: var(--error-subtle);
}
.badge--muted {
  color: var(--ink-1);
  background: var(--bg-3);
}
</style>
