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
    <input class="rs-cf-range" type="range" min="1" max="13" :value="props.filter.coverMax ?? 13"
      @input="patch({ coverMax: Number(($event.target as HTMLInputElement).value) })" />
    <input class="rs-search" type="search" :value="props.filter.search"
      @input="patch({ search: ($event.target as HTMLInputElement).value.trim() })" />
    <button class="rs-reset" @click="emit('update', { ...RESET_FILTER })">重置</button>
  </div>
</template>
