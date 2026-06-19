<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRecentChangesStore } from "../../stores/recentChanges";
import type { ChangeRowVM } from "./recent-changes-types";

const emit = defineEmits<{ (e: "drill", barcode: string): void }>();
const store = useRecentChangesStore();

// === Chinese label maps (1:1 from index-recent-changes.js) ===
const FIELD_CN: Record<string, string> = {
  stockpile_location: "库位",
  product_model: "型号",
  product_barcode: "条码",
  is_active: "上下架",
};
const CHANGE_TYPE_CN: Record<string, string> = {
  update: "更新",
  insert: "新增",
  deactivate: "下架",
  reactivate: "上架",
};

// 海量批次只渲染前 N 行，避免 DOM 卡死
const RENDER_CAP = 300;

onMounted(() => {
  store.ensureLoaded();
});

// === batch dropdown ===
function batchOptionText(b: {
  isOpen: boolean;
  affectedBarcodes: number;
  takenAt: string | null;
  totalLocal: number | null;
}): string {
  if (b.isOpen) {
    return `🔄 进行中（上次 import 之后） — 改动 ${b.affectedBarcodes} 个货号 · 最近 ${b.takenAt || "—"}`;
  }
  return `${b.takenAt || "—"} （${b.totalLocal ?? 0} 条 / 改动 ${b.affectedBarcodes} 个货号）`;
}
function onBatchChange(e: Event) {
  const value = (e.target as HTMLSelectElement).value;
  store.selectBatch(Number(value));
}

// === stat boxes ===
interface StatCell {
  label: string;
  n: number;
  field: string | null;
  changeType: string | null;
  baseTone: string;
}
const statCells = computed<StatCell[]>(() => {
  const s = store.summary;
  return [
    { label: "库位变更", n: s?.locationChanges ?? 0, field: "stockpile_location", changeType: null, baseTone: "default" },
    { label: "型号变更", n: s?.modelChanges ?? 0, field: "product_model", changeType: null, baseTone: "info" },
    { label: "新增", n: s?.inserts ?? 0, field: null, changeType: "insert", baseTone: "accent" },
    { label: "失效", n: s?.deactivates ?? 0, field: null, changeType: "deactivate", baseTone: "error" },
    { label: "重新上架", n: s?.reactivates ?? 0, field: null, changeType: "reactivate", baseTone: "warn" },
  ];
});
function statTone(c: StatCell): string {
  return c.n > 0 ? c.baseTone : "default";
}
function onStatClick(c: StatCell) {
  store.setFilter({ field: c.field, changeType: c.changeType });
}

// === filter chips ===
interface Chip {
  label: string;
  n: number;
  field: string | null;
  changeType: string | null;
}
const chips = computed<Chip[]>(() => {
  const s = store.summary;
  const total =
    (s?.locationChanges ?? 0) + (s?.modelChanges ?? 0) + (s?.inserts ?? 0) + (s?.deactivates ?? 0) + (s?.reactivates ?? 0);
  const base: Chip[] = [
    { label: "全部", n: total, field: null, changeType: null },
    { label: "仅库位", n: s?.locationChanges ?? 0, field: "stockpile_location", changeType: null },
    { label: "仅型号", n: s?.modelChanges ?? 0, field: "product_model", changeType: null },
    { label: "仅新增", n: s?.inserts ?? 0, field: null, changeType: "insert" },
    { label: "仅失效", n: s?.deactivates ?? 0, field: null, changeType: "deactivate" },
  ];
  if (store.mode === "raw") {
    base.push({ label: "仅 update", n: 0, field: null, changeType: "update" });
    base.push({ label: "仅 reactivate", n: s?.reactivates ?? 0, field: null, changeType: "reactivate" });
  }
  return base;
});
function chipActive(c: Chip): boolean {
  return c.field === store.filter.field && c.changeType === store.filter.changeType;
}
function onChipClick(c: Chip) {
  store.setFilter({ field: c.field, changeType: c.changeType });
}
const hasSummary = computed(() => store.summary !== null);

// === mode toggle ===
function toggleMode() {
  store.setMode(store.mode === "collapsed" ? "raw" : "collapsed");
}

// === change list ===
const visibleChanges = computed(() => store.changes.slice(0, RENDER_CAP));
const showCapNote = computed(() => store.totalCount > RENDER_CAP);
function fmtTime(at: string): string {
  return (at || "").slice(11, 19);
}
function fieldCn(field: string): string {
  return FIELD_CN[field] || field;
}
function typeCn(changeType: string): string {
  return CHANGE_TYPE_CN[changeType] || changeType;
}

// renderChangeCell helpers (collapsed mode)
function isLoc(r: ChangeRowVM): boolean {
  return r.field === "stockpile_location";
}
function isModel(r: ChangeRowVM): boolean {
  return r.field === "product_model";
}
function changeFieldLabel(r: ChangeRowVM): string {
  if (isLoc(r)) return "库位";
  if (isModel(r)) return "型号";
  return FIELD_CN[r.field] || r.field;
}
function onRowClick(barcode: string) {
  emit("drill", barcode);
}
</script>

<template>
  <section class="rc">
    <!-- batches loading / error / empty -->
    <p v-if="store.loading" class="rc-msg">批次加载中…</p>

    <div v-else-if="store.error" class="rc-error rc-error--bar">
      加载失败：{{ store.error }}
      <button type="button" class="rc-retry" @click="store.ensureLoaded()">重试</button>
    </div>

    <div v-else-if="store.loaded && !store.batches.length" class="rc-empty">还没有 import 记录</div>

    <template v-else-if="store.batches.length">
      <!-- batch dropdown -->
      <div class="rc-batch-bar">
        <select class="rc-batch-select" :value="store.selectedBatchId ?? undefined" @change="onBatchChange">
          <option v-for="b in store.batches" :key="b.batchId" :value="b.batchId">{{ batchOptionText(b) }}</option>
        </select>
      </div>

      <!-- summary stat boxes -->
      <div class="rc-summary">
        <div class="rc-stats">
          <button
            v-for="c in statCells"
            :key="c.label"
            type="button"
            class="rc-stat"
            :data-tone="statTone(c)"
            @click="onStatClick(c)"
          >
            <div class="rc-stat-num">{{ c.n }}</div>
            <div class="rc-stat-label">{{ c.label }}</div>
          </button>
        </div>
        <div class="rc-roundtrip-note">
          来回波动 <b>{{ store.summary?.roundtripCount ?? 0 }}</b> 组 · 同 barcode + 字段终态==起始态的折叠剔除噪音
        </div>
      </div>

      <!-- chips + mode toggle -->
      <div class="rc-controls">
        <div class="rc-chips">
          <button
            v-for="c in chips"
            :key="c.label"
            type="button"
            class="rc-chip"
            :class="{ 'rc-chip--active': chipActive(c) }"
            @click="onChipClick(c)"
          >
            {{ c.label }}<span v-if="hasSummary" class="rc-chip-count">{{ c.n }}</span>
          </button>
        </div>
        <button type="button" class="rc-mode-toggle" :data-mode="store.mode" @click="toggleMode">
          {{ store.mode === "collapsed" ? "展开 raw 事件" : "折叠净效应" }}
        </button>
      </div>

      <!-- detail sub-states -->
      <p v-if="store.detailLoading" class="rc-msg">加载中…</p>

      <div v-else-if="store.detailError" class="rc-error rc-error--bar">
        加载失败：{{ store.detailError }}
        <button type="button" class="rc-retry" @click="store.loadDetail()">重试当前批次</button>
      </div>

      <div v-else-if="!store.changes.length" class="rc-empty">该批次无实质变更</div>

      <!-- collapsed list -->
      <template v-else-if="store.mode === 'collapsed'">
        <table class="rc-tbl">
          <thead>
            <tr><th>货号</th><th>型号</th><th>变化</th><th>时间</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="(r, i) in visibleChanges"
              :key="i"
              class="rc-row"
              :data-barcode="r.barcode"
              @click="onRowClick(r.barcode)"
            >
              <td>{{ r.barcode }}</td>
              <td>{{ r.model || "" }}</td>
              <td>
                <span v-if="r.changeType === 'insert'" class="rc-tag rc-tag--insert">
                  <span class="rc-tag-glyph">+</span>新货号 → {{ r.toValue || r.barcode }}
                </span>
                <span v-else-if="r.changeType === 'deactivate'" class="rc-tag rc-tag--del">
                  <span class="rc-tag-glyph">✕</span>失效
                </span>
                <span v-else-if="r.changeType === 'reactivate'" class="rc-tag rc-tag--ok">
                  <span class="rc-tag-glyph">↺</span>重新上架
                </span>
                <span v-else :class="isLoc(r) ? 'rc-change-loc' : isModel(r) ? 'rc-change-model' : ''">
                  {{ changeFieldLabel(r) }}
                  <template v-if="r.fromValue">
                    <span class="rc-change-from">{{ r.fromValue }}</span><span class="rc-change-arrow">→</span>
                  </template>
                  <span
                    :class="isLoc(r) ? 'rc-change-to rc-change-to--loc' : isModel(r) ? 'rc-change-to rc-change-to--model' : 'rc-change-to'"
                  >{{ r.toValue || "" }}</span>
                </span>
              </td>
              <td class="rc-time">{{ fmtTime(r.at) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="showCapNote" class="rc-roundtrip-note">
          仅显示前 {{ RENDER_CAP }} / 共 {{ store.totalCount.toLocaleString() }} 条 · 用上方筛选缩小范围
        </div>
      </template>

      <!-- raw list -->
      <template v-else>
        <table class="rc-tbl">
          <thead>
            <tr><th>货号</th><th>型号</th><th>字段</th><th>旧值</th><th>新值</th><th>类型</th><th>时间</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="(r, i) in visibleChanges"
              :key="i"
              class="rc-row"
              :data-barcode="r.barcode"
              @click="onRowClick(r.barcode)"
            >
              <td>{{ r.barcode }}</td>
              <td>{{ r.model || "" }}</td>
              <td>{{ fieldCn(r.field) }}</td>
              <td><code>{{ r.fromValue ?? "" }}</code></td>
              <td><code>{{ r.toValue ?? "" }}</code></td>
              <td><span class="rc-tag">{{ typeCn(r.changeType) }}</span></td>
              <td class="rc-time">{{ fmtTime(r.at) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="showCapNote" class="rc-roundtrip-note">
          仅显示前 {{ RENDER_CAP }} / 共 {{ store.totalCount.toLocaleString() }} 条 · 用上方筛选缩小范围
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
.rc { display: flex; flex-direction: column; gap: var(--sp-3); }
.rc-msg { color: var(--ink-2); }
.rc-empty { color: var(--ink-2); padding: var(--sp-3) 0; }
.rc-error { color: var(--error); }
.rc-error--bar { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-2) var(--sp-3); border: 1px solid var(--error); border-radius: var(--r-sm); }
.rc-retry { padding: 2px 10px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: transparent; color: var(--ink-0); cursor: pointer; }

.rc-batch-bar { margin-bottom: var(--sp-2); }
.rc-batch-select { width: 100%; padding: var(--sp-2) var(--sp-3); border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: transparent; color: var(--ink-0); }

.rc-stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: var(--sp-2); margin-bottom: var(--sp-2); }
.rc-stat { display: flex; flex-direction: column; gap: 2px; align-items: center; padding: var(--sp-3); border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: transparent; color: var(--ink-1); cursor: pointer; }
.rc-stat-num { font-size: var(--fs-xl); font-weight: 700; font-family: var(--mono); }
.rc-stat-label { font-size: var(--fs-sm); color: var(--ink-2); }
.rc-stat[data-tone="accent"] .rc-stat-num { color: var(--accent); }
.rc-stat[data-tone="info"] .rc-stat-num { color: var(--info, var(--accent)); }
.rc-stat[data-tone="warn"] .rc-stat-num { color: var(--warn); }
.rc-stat[data-tone="error"] .rc-stat-num { color: var(--error); }
.rc-roundtrip-note { font-size: var(--fs-sm); color: var(--ink-2); }

.rc-controls { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); flex-wrap: wrap; }
.rc-chips { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
.rc-chip { font-size: var(--fs-sm); padding: 2px 10px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: transparent; color: var(--ink-1); cursor: pointer; display: inline-flex; align-items: center; gap: var(--sp-1); }
.rc-chip--active { background: var(--accent-subtle); color: var(--accent); border-color: var(--accent); }
.rc-chip-count { font-family: var(--mono); color: var(--ink-3); }
.rc-mode-toggle { font-size: var(--fs-sm); padding: 2px 10px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: transparent; color: var(--ink-1); cursor: pointer; }

.rc-tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.rc-tbl th, .rc-tbl td { padding: var(--sp-2) var(--sp-3); text-align: left; border-bottom: 1px solid var(--line-soft); }
.rc-row { cursor: pointer; }
.rc-row:hover { background: var(--accent-subtle); }
.rc-time { font-family: var(--mono); color: var(--ink-2); }

.rc-tag { display: inline-flex; align-items: center; gap: 4px; font-size: var(--fs-xs); padding: 1px 6px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); }
.rc-tag-glyph { font-weight: 700; }
.rc-tag--insert { color: var(--accent); border-color: var(--accent); }
.rc-tag--del { color: var(--error); border-color: var(--error); }
.rc-tag--ok { color: var(--warn); border-color: var(--warn); }

.rc-change-arrow { color: var(--ink-3); margin: 0 4px; }
.rc-change-from { color: var(--ink-3); }
.rc-change-to { font-family: var(--mono); }
.rc-change-to--loc { color: var(--accent); }
.rc-change-to--model { color: var(--info, var(--accent)); }
</style>
