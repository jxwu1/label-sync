<script setup lang="ts">
import { ref } from "vue";
import PageHeader from "../../components/PageHeader.vue";
import { useHistoryStore } from "../../stores/history";

const store = useHistoryStore();
const q = ref("");

const SOURCE_CN: Record<string, string> = {
  scan_import: "扫描导入", user_correction: "手动修正",
  system_export: "系统导出", inventory_events: "进销存",
};
const FIELD_CN: Record<string, string> = {
  stockpile_location: "库位", product_model: "型号",
  product_barcode: "条码", is_active: "上下架",
};
const CHANGE_TYPE_CN: Record<string, string> = {
  update: "更新", insert: "新增", deactivate: "下架",
  reactivate: "上架", sale: "销售", purchase: "采购",
};
const cn = (m: Record<string, string>, k: string | null) => (k ? m[k] ?? k : "");

function doSearch() {
  const v = q.value.trim();
  if (v) store.load(v);
}
function pickFuzzy(barcode: string) {
  q.value = barcode;
  store.load(barcode);
}
async function copyBarcode(bc: string) {
  // 内网 HTTP 非 secure context：navigator.clipboard 可能不可用 → execCommand 兜底
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(bc); return; } catch { /* fall through */ }
  }
  const ta = document.createElement("textarea");
  ta.value = bc; ta.style.position = "fixed"; ta.style.left = "-9999px";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); } catch { /* ignore */ }
  document.body.removeChild(ta);
}
</script>

<template>
  <main class="history">
    <PageHeader title="货号历史" subtitle="核心查询 / 变更溯源（完整分析见旧版）" />

    <!-- HC-1 安全阀：完整分析旧版深链 -->
    <a class="history__legacy-link" href="/?page=history">查看完整分析（旧版）→</a>

    <div class="history__search">
      <input
        v-model="q" class="history__input" type="text" placeholder="输入条码 / 型号后查询"
        @keydown.enter="doSearch" />
      <button class="history__btn" type="button" @click="doSearch">⌕ 查询</button>
      <button class="history__btn history__btn--ghost" type="button" @click="q = ''; store.result = null">↺ 重置</button>
    </div>

    <p v-if="store.loading" class="history__msg">查询中…</p>
    <p v-else-if="store.error" class="history__error">{{ store.error }}</p>
    <p v-else-if="!store.result" class="history__msg">输入条码或型号后查询历史</p>

    <template v-else-if="store.result.kind === 'notfound'">
      <p class="history__msg">未找到 "{{ q }}"，请检查型号或条码是否正确</p>
    </template>

    <template v-else-if="store.result.kind === 'fuzzy'">
      <div class="history__fuzzy">
        <div class="history__fuzzy-hd">候选匹配（精确未命中，点击选择）</div>
        <table class="history__table">
          <thead><tr><th>条码</th><th>型号</th><th>当前位置</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="m in store.result.matches" :key="m.barcode" class="history__fuzzy-row" @click="pickFuzzy(m.barcode)">
              <td>{{ m.barcode }}</td><td>{{ m.model }}</td><td>{{ m.location ?? "—" }}</td>
              <td>{{ m.isActive ? "活跃" : "已下架" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <template v-else-if="store.result.kind === 'hit'">
      <div class="history__hero">
        <span class="history__model">{{ store.result.current.model || "—" }}</span>
        <span class="history__barcode">{{ store.result.current.barcode }}</span>
        <span class="history__pill" :class="store.result.current.isTrulyDiscontinued ? 'is-off' : 'is-on'">
          {{ store.result.current.isTrulyDiscontinued ? "已停售" : "在售" }}
        </span>
        <span v-if="store.result.current.manualGrade !== null" class="history__grade">{{ store.result.current.manualGrade }}</span>
        <button class="history__btn history__btn--ghost" type="button" @click="copyBarcode(store.result.current.barcode)">⎘ 复制</button>
      </div>

      <dl class="history__overview">
        <template v-if="store.result.current.productNameZh"><dt>品名</dt><dd>{{ store.result.current.productNameZh }}</dd></template>
        <template v-if="store.result.current.productNameLocal"><dt>本地品名</dt><dd>{{ store.result.current.productNameLocal }}</dd></template>
        <dt>店面位置</dt><dd>{{ store.result.current.storeLocations.join(", ") || "—" }}</dd>
        <dt>仓库位置</dt><dd>{{ store.result.current.warehouseLocations.join(", ") || "—" }}</dd>
        <template v-if="store.result.current.unknownLocations.length"><dt>其他位置</dt><dd>{{ store.result.current.unknownLocations.join(", ") }}</dd></template>
        <template v-if="store.result.current.salePrice !== null"><dt>售价</dt><dd>€{{ store.result.current.salePrice.toFixed(2) }}</dd></template>
        <dt>来源</dt><dd>{{ cn(SOURCE_CN, store.result.current.source) || "—" }}</dd>
        <dt>最后更新</dt><dd>{{ store.result.current.updatedAt ?? "—" }}</dd>
      </dl>

      <div class="history__timeline">
        <div class="history__timeline-hd">历史时间线</div>
        <p v-if="!store.result.events.length" class="history__msg">暂无历史变更</p>
        <div v-else>
          <div class="history__count">共 {{ store.result.events.length }} 次操作</div>
          <div v-for="(ev, i) in store.result.events" :key="i" class="history__evt">
            <div class="history__evt-head">
              <span class="history__evt-type">{{ cn(CHANGE_TYPE_CN, ev.changeType) }}</span>
              <span class="history__evt-src">{{ cn(SOURCE_CN, ev.source) }}</span>
              <span class="history__evt-time">{{ ev.at }}</span>
            </div>
            <div v-if="ev.summary" class="history__evt-detail">{{ ev.summary }}</div>
            <div v-else-if="ev.changes.length" class="history__evt-detail">
              <div v-for="(ch, j) in ev.changes" :key="j">
                <span class="history__evt-field">{{ cn(FIELD_CN, ch.field) }}</span>
                <code>{{ ch.old || "空" }}</code> → <code>{{ ch.new || "空" }}</code>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </main>
</template>

<style scoped>
.history { padding: var(--sp-6); max-width: 1100px; margin: 0 auto; }
.history__legacy-link { display: inline-block; margin-bottom: var(--sp-4); font-size: var(--fs-sm); color: var(--accent); }
.history__search { display: flex; gap: var(--sp-2); margin-bottom: var(--sp-4); }
.history__input { flex: 1; padding: var(--sp-2) var(--sp-3); border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: transparent; color: var(--ink-0); }
.history__btn { padding: var(--sp-2) var(--sp-4); border: 1px solid var(--line-soft); border-radius: var(--r-sm); cursor: pointer; color: var(--ink-0); }
.history__btn--ghost { background: transparent; }
.history__msg { color: var(--ink-2); }
.history__error { color: var(--error); }
.history__fuzzy-hd, .history__timeline-hd { font-size: var(--fs-sm); color: var(--ink-2); margin-bottom: var(--sp-2); }
.history__table { width: 100%; border-collapse: collapse; }
.history__table th, .history__table td { padding: var(--sp-2) var(--sp-3); text-align: left; border-bottom: 1px solid var(--line-soft); font-size: var(--fs-sm); }
.history__fuzzy-row { cursor: pointer; }
.history__fuzzy-row:hover { background: var(--accent-subtle); }
.history__hero { display: flex; align-items: center; gap: var(--sp-3); margin-bottom: var(--sp-4); flex-wrap: wrap; }
.history__model { font-size: var(--fs-xl); font-weight: 700; }
.history__barcode { font-family: var(--mono); color: var(--ink-2); }
.history__pill { font-size: var(--fs-sm); padding: 2px 8px; border-radius: var(--r-sm); }
.history__pill.is-on { background: var(--accent-subtle); color: var(--accent); }
.history__pill.is-off { background: var(--warn-subtle); color: var(--warn); }
.history__grade { font-family: var(--mono); font-weight: 700; padding: 2px 8px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); }
.history__overview { display: grid; grid-template-columns: max-content 1fr; gap: var(--sp-2) var(--sp-4); margin-bottom: var(--sp-6); }
.history__overview dt { color: var(--ink-2); font-size: var(--fs-sm); }
.history__overview dd { font-family: var(--mono); }
.history__count { font-size: var(--fs-sm); color: var(--ink-2); margin-bottom: var(--sp-2); }
.history__evt { padding: var(--sp-2) 0; border-bottom: 1px solid var(--line-soft); }
.history__evt-head { display: flex; gap: var(--sp-3); font-size: var(--fs-sm); }
.history__evt-type { font-weight: 600; }
.history__evt-src, .history__evt-time { color: var(--ink-2); }
.history__evt-detail { margin-top: var(--sp-1); font-size: var(--fs-sm); }
.history__evt-field { color: var(--ink-3); margin-right: var(--sp-2); }
</style>
