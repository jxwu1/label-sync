<script setup lang="ts">
import type { SupplierRow } from "./supplier-summary";
defineOptions({ name: "SupplierOverview" });
const props = defineProps<{ rows: SupplierRow[]; expanded: boolean; activeSupplier: string | null }>();
const emit = defineEmits<{ (e: "select-supplier", bc: string): void; (e: "toggle-expand"): void }>();
</script>

<template>
  <div id="rsSupplierOverview" class="sup-strip">
    <span class="sup-strip-label"><span class="sup-fire">🔥</span> 紧迫供应商</span>
    <div class="sup-chips">
      <button v-for="s in props.rows" :key="s.supplier_id"
        :class="['sup-chip', { 'is-hot': s.hot_count > 0, 'is-active': s.supplier_id === props.activeSupplier }]"
        @click="emit('select-supplier', s.supplier_id)">
        <span class="sup-chip-name">{{ s.supplier_id }}</span>
        <span class="sup-chip-cnt">{{ s.count }}</span>
        <span class="sup-chip-score">{{ Math.round(s.max) }}</span>
      </button>
    </div>
    <button class="sup-strip-more" @click="emit('toggle-expand')">{{ props.expanded ? "‹ 收起" : "查看全部 ›" }}</button>
  </div>
</template>

<style scoped>
.sup-strip { display: flex; align-items: center; gap: 8px; padding: 10px 20px; background: var(--bg-1); border-bottom: 1px solid var(--line-soft); flex-shrink: 0; }
.sup-strip-label { display: flex; align-items: center; gap: 5px; font-size: var(--fs-xs); font-weight: 600; color: var(--ink-2); text-transform: uppercase; letter-spacing: 0.03em; white-space: nowrap; flex-shrink: 0; }
.sup-strip-label .sup-fire { color: var(--accent); font-size: 11px; }
.sup-chips { display: flex; gap: 6px; flex: 1; overflow-x: auto; padding-bottom: 2px; }
.sup-chips::-webkit-scrollbar { height: 0; }
.sup-chip { display: inline-flex; align-items: center; gap: 8px; flex-shrink: 0; padding: 5px 10px; background: var(--bg-0); border: 1px solid var(--line-soft); border-radius: var(--r-sm); cursor: pointer; transition: all var(--t-fast); }
.sup-chip:hover { border-color: var(--line); background: var(--bg-2); }
.sup-chip.is-hot { border-color: var(--accent-subtle-border); background: var(--accent-subtle); }
.sup-chip.is-active { border-color: var(--accent); }
.sup-chip-name { font-size: var(--fs-sm); font-weight: 600; color: var(--ink-0); font-family: var(--mono); white-space: nowrap; }
.sup-chip-cnt { font-family: var(--mono); font-size: var(--fs-xs); font-weight: 700; color: var(--ink-2); padding: 1px 5px; background: var(--bg-3); border-radius: 2px; }
.sup-chip.is-hot .sup-chip-cnt { color: var(--accent); background: var(--accent-subtle); }
.sup-chip-score { font-family: var(--mono); font-size: 9px; font-weight: 600; color: var(--ink-3); }
.sup-chip.is-hot .sup-chip-score { color: var(--accent); }
.sup-strip-more { font-size: var(--fs-xs); color: var(--ink-2); font-weight: 600; background: none; border: none; cursor: pointer; white-space: nowrap; flex-shrink: 0; padding: 4px 8px; border-radius: var(--r-sm); transition: all var(--t-fast); }
.sup-strip-more:hover { background: var(--bg-2); color: var(--ink-0); }
</style>
