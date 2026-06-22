<script setup lang="ts">
import { RESET_FILTER, type FilterState } from "./constants";
const props = defineProps<{ filter: FilterState }>();
const emit = defineEmits<{ (e: "update", f: FilterState): void }>();

function patch(p: Partial<FilterState>) { emit("update", { ...props.filter, ...p }); }
function setView(k: "active" | "new" | "disc") {
  patch({ views: { ...props.filter.views, [k]: !props.filter.views[k] } });
}
const ORIGINS: [string, string][] = [["", "全部"], ["FOREIGN", "国外"], ["CN", "国内"], ["unknown", "未知"]];
const VIEWS: ["active" | "new" | "disc", string][] = [["active", "活跃"], ["new", "新品"], ["disc", "含停用"]];
const BANDS: [string, string][] = [["all", "全部"], ["urgent", "紧急"], ["watch", "关注"], ["ok", "充足"], ["skipped", "已跳过"]];
</script>

<template>
  <div id="rsFilterBar" class="rs-filterbar">
    <div id="rsOriginSeg" class="rs-origin-seg">
      <button v-for="[v, l] in ORIGINS" :key="v" :data-origin="v"
        :class="['rs-origin-btn', { on: (props.filter.origin || '') === v }]" @click="patch({ origin: v })">{{ l }}</button>
    </div>
    <div class="rs-vchips">
      <button v-for="[k, l] in VIEWS" :key="k" :data-view="k"
        :class="['rs-vchip', { on: props.filter.views[k] }]" @click="setView(k)">{{ l }}</button>
    </div>
    <div class="rs-bands">
      <button v-for="[v, l] in BANDS" :key="v" :data-band="v"
        :class="['rs-chip', { 'rs-chip--active': props.filter.band === v }]"
        @click="patch({ band: props.filter.band === v ? 'all' : v })">{{ l }}</button>
    </div>
    <span v-if="props.filter.supplier" class="rs-supplier-tag">
      <span class="rs-supplier-tag-label">供应商</span>
      <span class="rs-supplier-tag-val">{{ props.filter.supplier }}</span>
      <button type="button" class="rs-supplier-tag-x" title="清除供应商筛选" @click="patch({ supplier: null })">×</button>
    </span>
    <span class="rs-f-sep"></span>
    <label class="rs-cf">
      <span class="rs-cf-label">可撑</span>
      <input class="rs-cf-range" type="range" min="0.5" max="20" step="0.5" :value="props.filter.coverMax ?? 4"
        @input="patch({ coverMax: Number(($event.target as HTMLInputElement).value) })" />
      <span class="rs-cf-val">{{ props.filter.coverMax != null ? "≤ " + props.filter.coverMax + "w" : "不限" }}</span>
      <button v-if="props.filter.coverMax != null" type="button" class="rs-cf-clear"
        title="不限" @click="patch({ coverMax: null })">×</button>
    </label>
    <span class="rs-f-spacer"></span>
    <input class="rs-search" type="search" placeholder="供应商 / 条码 / 型号 / 品名" :value="props.filter.search"
      @input="patch({ search: ($event.target as HTMLInputElement).value.trim() })" />
    <button class="rs-reset" @click="emit('update', { ...RESET_FILTER })">重置</button>
  </div>
</template>

<style scoped>
.rs-filterbar { display: flex; align-items: center; gap: 8px; padding: 10px 20px; background: var(--bg-1); border-bottom: 1px solid var(--line-soft); flex-wrap: wrap; }

/* 来源分段控件（旧 .rs-seg） */
.rs-origin-seg { display: inline-flex; background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: var(--r-sm); padding: 2px; gap: 2px; }
.rs-origin-btn { display: inline-flex; align-items: center; padding: 3px 10px; border: none; background: transparent; border-radius: 3px; font-size: var(--fs-sm); font-weight: 600; color: var(--ink-2); cursor: pointer; font-family: var(--sans); transition: all var(--t-fast); white-space: nowrap; }
.rs-origin-btn:hover { color: var(--ink-0); }
.rs-origin-btn.on { background: var(--bg-4); color: var(--ink-0); box-shadow: var(--sh-sm); }

/* 视图开关 chip（旧 .rs-vchip / .rs-chip） */
.rs-vchips, .rs-bands { display: inline-flex; gap: 6px; }
.rs-vchip, .rs-chip { padding: 4px 10px; border-radius: var(--r-sm); font-size: var(--fs-sm); font-weight: 600; color: var(--ink-2); background: transparent; border: 1px solid var(--line-soft); cursor: pointer; transition: all var(--t-fast); white-space: nowrap; }
.rs-vchip:hover, .rs-chip:hover { background: var(--bg-2); color: var(--ink-1); }
.rs-vchip.on, .rs-chip--active { background: var(--accent-subtle); color: var(--accent); border-color: var(--accent-subtle-border); }

.rs-f-sep { width: 1px; height: 16px; background: var(--line-soft); flex-shrink: 0; }
.rs-f-spacer { flex: 1; }

/* 当前供应商筛选标签 + 清除（旧 .rs-supplier-tag） */
.rs-supplier-tag { display: inline-flex; align-items: center; gap: 4px; padding: 3px 6px 3px 10px; border-radius: var(--r-sm); background: var(--accent-subtle); border: 1px solid var(--accent-subtle-border); }
.rs-supplier-tag-label { font-size: var(--fs-xs); font-weight: 600; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.03em; }
.rs-supplier-tag-val { font-family: var(--mono); font-size: var(--fs-sm); font-weight: 600; color: var(--accent); }
.rs-supplier-tag-x { background: transparent; border: none; color: var(--accent); cursor: pointer; font-size: 13px; line-height: 1; padding: 0 0 0 2px; }
.rs-supplier-tag-x:hover { color: var(--error); }

/* 可撑滑块 */
.rs-cf { display: inline-flex; align-items: center; gap: 6px; }
.rs-cf-label { font-size: var(--fs-xs); font-weight: 600; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.03em; }
.rs-cf-range { width: 110px; accent-color: var(--accent); }
.rs-cf-val { font-family: var(--mono); font-size: var(--fs-sm); color: var(--accent); min-width: 44px; }
.rs-cf-clear { border: none; background: none; color: var(--ink-3); cursor: pointer; font-size: 13px; line-height: 1; padding: 0 2px; }
.rs-cf-clear:hover { color: var(--error); }

/* 搜索框 */
.rs-search { padding: 5px 10px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: var(--bg-0); font-family: var(--sans); font-size: var(--fs-sm); color: var(--ink-0); width: 200px; outline: none; transition: border-color var(--t-fast); }
.rs-search:focus { border-color: var(--accent); }
.rs-search::placeholder { color: var(--ink-3); }

/* 重置键 */
.rs-reset { display: inline-flex; align-items: center; gap: 5px; padding: 4px 10px; border-radius: var(--r-sm); font-size: var(--fs-sm); font-weight: 600; color: var(--ink-2); background: transparent; border: 1px solid var(--line-soft); cursor: pointer; transition: all var(--t-fast); white-space: nowrap; }
.rs-reset:hover { border-color: var(--accent-subtle-border); color: var(--accent); background: var(--accent-subtle); }
</style>
