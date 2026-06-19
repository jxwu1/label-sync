<script setup lang="ts">
import { onMounted } from "vue";
import { useScanBatchesStore } from "../../stores/scanBatches";
import type { ScanBatchVM } from "./scan-batch-types";

defineOptions({ name: "ScanBatchPanel" });

const store = useScanBatchesStore();
onMounted(() => { store.ensureLoaded(); });

function csvUrl(b: ScanBatchVM) {
  return `/scan_history/batches/${encodeURIComponent(b.batchId)}/download/csv`;
}
function zipUrl(b: ScanBatchVM) {
  return `/scan_history/batches/${encodeURIComponent(b.batchId)}/download/zip`;
}
function fileUrl(b: ScanBatchVM, name: string) {
  return `/scan_history/batches/${encodeURIComponent(b.batchId)}/files/${encodeURIComponent(name)}`;
}
function fmtBytes(n: number | null): string {
  if (n === null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
function summary(b: ScanBatchVM): string {
  const csv = b.csvRows !== null ? `${b.csvRows} 行` : "无 CSV";
  const xlsx = b.xlsxFiles.length ? `${b.xlsxFiles.length} 个 xlsx` : "";
  return [csv, xlsx].filter(Boolean).join(" · ");
}
function onEmployeeChange(e: Event) {
  const v = (e.target as HTMLSelectElement).value;
  store.setEmployeeFilter(v === "" ? null : v);
}
</script>

<template>
  <div class="sb">
    <div v-if="store.error" class="sb-error">
      加载失败：{{ store.error }}
      <button type="button" class="sb-retry" @click="store.ensureLoaded()">重试</button>
    </div>

    <div v-else-if="store.loading || !store.loaded" class="sb-loading">加载中…</div>

    <template v-else>
      <div class="sb-toolbar">
        <select class="sb-employee" aria-label="筛选员工" :value="store.employeeFilter ?? ''" @change="onEmployeeChange">
          <option value="">全部员工</option>
          <option v-for="e in store.employees" :key="e" :value="e">{{ e }}</option>
        </select>
      </div>

      <div v-if="store.filteredBatches.length === 0" class="sb-empty">暂无批次</div>

      <div v-else class="sb-list">
        <div v-for="b in store.filteredBatches" :key="b.batchId" class="sb-row">
          <button
            type="button"
            class="sb-row-head"
            :aria-expanded="store.expanded.has(b.batchId)"
            @click="store.toggleExpand(b.batchId)">
            <span class="sb-time">{{ b.scannedAt }}</span>
            <span class="sb-emp">{{ b.employee }}</span>
            <span class="sb-meta">{{ summary(b) }}</span>
            <span class="sb-chevron">{{ store.expanded.has(b.batchId) ? "▼" : "▶" }}</span>
          </button>

          <div v-if="store.expanded.has(b.batchId)" class="sb-detail">
            <div v-if="b.csvFilename" class="sb-file">
              📄 {{ b.csvFilename }} · {{ b.csvRows != null ? b.csvRows + ' 行' : '行数未知' }} · {{ fmtBytes(b.csvSizeBytes) }}
              <a class="sb-dl" :href="csvUrl(b)">下载</a>
            </div>
            <div v-else class="sb-file sb-file--muted">📄 CSV 缺失</div>

            <div v-for="f in b.xlsxFiles" :key="f.name" class="sb-file">
              📊 {{ f.name }} · {{ fmtBytes(f.sizeBytes) }}
              <a class="sb-dl" :href="fileUrl(b, f.name)">下载</a>
            </div>

            <div v-if="b.csvFilename || b.xlsxFiles.length" class="sb-file sb-file--zip">
              🗜 <a class="sb-dl" :href="zipUrl(b)">下载全部 ZIP</a>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sb { display: flex; flex-direction: column; gap: var(--sp-3); }
.sb-error { padding: var(--sp-3); color: var(--error); }
.sb-retry { margin-left: var(--sp-2); padding: 2px 10px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: transparent; color: var(--ink-0); cursor: pointer; }
.sb-employee { padding: 4px 8px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: transparent; color: var(--ink-0); }
.sb-loading { padding: var(--sp-4); color: var(--ink-3); }
.sb-empty { padding: var(--sp-4); color: var(--ink-3); }
.sb-row { border-bottom: 1px solid var(--line-soft); }
.sb-row-head { display: flex; gap: var(--sp-3); align-items: center; width: 100%; padding: var(--sp-2) 0; background: transparent; border: none; color: var(--ink-0); cursor: pointer; text-align: left; }
.sb-emp { color: var(--accent); }
.sb-meta { color: var(--ink-2); }
.sb-chevron { margin-left: auto; color: var(--ink-3); }
.sb-detail { padding: 0 0 var(--sp-2) var(--sp-3); display: flex; flex-direction: column; gap: 4px; }
.sb-file { font-size: var(--fs-sm); }
.sb-file--muted { color: var(--ink-3); }
.sb-dl { margin-left: var(--sp-2); color: var(--accent); }
</style>
