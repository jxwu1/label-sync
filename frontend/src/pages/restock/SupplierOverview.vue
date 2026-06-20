<script setup lang="ts">
import type { SupplierRow } from "./supplier-summary";
defineOptions({ name: "SupplierOverview" });
const props = defineProps<{ rows: SupplierRow[]; expanded: boolean; activeSupplier: string | null }>();
const emit = defineEmits<{ (e: "select-supplier", bc: string): void; (e: "toggle-expand"): void }>();
</script>

<template>
  <div id="rsSupplierOverview" class="sup-strip">
    <button v-for="s in props.rows" :key="s.supplier_id"
      :class="['sup-chip', { 'is-active': s.supplier_id === props.activeSupplier }]"
      @click="emit('select-supplier', s.supplier_id)">
      <span class="sup-chip-name">{{ s.supplier_id }}</span>
      <span class="sup-chip-cnt">{{ s.count }}</span>
      <span class="sup-chip-score">{{ Math.round(s.max) }}</span>
    </button>
    <button class="sup-strip-more" @click="emit('toggle-expand')">{{ props.expanded ? "‹ 收起" : "查看全部 ›" }}</button>
  </div>
</template>
