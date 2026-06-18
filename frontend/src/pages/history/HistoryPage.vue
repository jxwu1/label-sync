<script setup lang="ts">
import { ref } from "vue";
import PageHeader from "../../components/PageHeader.vue";
import { useHistoryStore } from "../../stores/history";
import { useSkuAnalyticsStore } from "../../stores/skuAnalytics";
import { useSkuExtrasStore } from "../../stores/skuExtras";
import { useSkuTimelineStore } from "../../stores/skuTimeline";
import TimelineChart from "./TimelineChart.vue";

const store = useHistoryStore();
const analyticsStore = useSkuAnalyticsStore();
const extrasStore = useSkuExtrasStore();
const timelineStore = useSkuTimelineStore();
const q = ref("");

const RECENT_KEY = "history.recentQueries";
const RECENT_MAX = 6;
const recent = ref<string[]>(loadRecent());

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter((x): x is string => typeof x === "string").slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}
function pushRecent(query: string) {
  const next = [query, ...recent.value.filter((x) => x !== query)].slice(0, RECENT_MAX);
  recent.value = next;
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(next)); } catch { /* ignore */ }
}
async function runSearch(query: string) {
  const fresh = await store.load(query);
  if (!fresh) return; // HC-B7: superseded search — don't touch downstream
  if (!store.error && store.result?.kind === "hit") {
    pushRecent(query);
    const bc = store.result.current.barcode;
    analyticsStore.load(bc);
    extrasStore.load(bc);
    timelineStore.load(bc);
  } else {
    analyticsStore.reset();
    extrasStore.reset();
    timelineStore.reset();
  }
}

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
const fmtPct = (v: number | null) => (v == null ? "—" : `${v}%`);
const eur = (v: number | null | undefined) => (v == null ? "—" : `€${Number(v).toFixed(2)}`);
const dayN = (v: number | null) => (v == null ? "—" : `${v} 天`);

// 2b local format helpers
const fmtNum = (v: number | null | undefined) => (v == null ? "—" : String(Math.round(v)));
const fmtNum2 = (v: number | null | undefined, d = 2) => (v == null ? "—" : Number(v).toFixed(d));
const fmtEurInt = (v: number | null | undefined) => (v == null ? "—" : `€${Math.round(Number(v))}`);

function doSearch() {
  const v = q.value.trim();
  if (v) runSearch(v);
}
function pickFuzzy(barcode: string) {
  q.value = barcode;
  runSearch(barcode);
}
function pickRecent(query: string) {
  q.value = query;
  runSearch(query);
}
function doReset() {
  q.value = "";
  store.reset();
  analyticsStore.reset();
  extrasStore.reset();
  timelineStore.reset();
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

// heatmap intensity helper (HC-B4: maxQty===0 → intensity 0, no divide-by-zero)
function heatIntensity(q: number, maxQty: number): number {
  if (maxQty === 0 || q === 0) return 0;
  return Math.max(0.12, q / maxQty);
}
function isPeak(q: number, maxQty: number): boolean {
  return q === maxQty && q > 0;
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
      <button class="history__btn history__btn--ghost" type="button" @click="doReset">↺ 重置</button>
    </div>

    <div v-if="recent.length" class="history__recent">
      <span class="history__recent-label">RECENT</span>
      <button
        v-for="r in recent" :key="r" type="button" class="history__recent-chip"
        @click="pickRecent(r)">{{ r }}</button>
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

      <!-- Phase 3: 走势图（概况后，SLA 前） -->
      <div class="history__timeline-chart">
        <div class="history__sec-hd">销售 / 进价走势</div>
        <p v-if="timelineStore.loading" class="history__msg">走势图加载中…</p>
        <p v-else-if="timelineStore.error" class="history__error history__timeline-chart-error">走势图加载失败：{{ timelineStore.error }}</p>
        <TimelineChart
          v-else-if="timelineStore.vm"
          :weeks="timelineStore.vm.weeks"
          :monthly-sales="timelineStore.vm.monthlySales"
        />
      </div>

      <!-- 2a: SLA + PUR + 客户拆分 -->
      <section class="history__analytics">
        <p v-if="analyticsStore.loading" class="history__msg">分析加载中…</p>
        <p v-else-if="analyticsStore.error" class="history__error">分析加载失败：{{ analyticsStore.error }}</p>
        <template v-else-if="analyticsStore.vm">
          <div class="history__sec-hd">销售分析</div>
          <div class="history__metrics">
            <div class="history__kv"><span>总销量</span><b>{{ analyticsStore.vm.sales.totalQty }}</b></div>
            <div class="history__kv"><span>总营收</span><b>{{ eur(analyticsStore.vm.sales.totalRevenue) }}</b></div>
            <div class="history__kv"><span>独立客户</span><b>{{ analyticsStore.vm.sales.uniqueCustomers }}</b></div>
            <div class="history__kv"><span>寿命</span><b>{{ analyticsStore.vm.sales.lifespanDays }} 天</b></div>
            <div class="history__kv"><span>12 周趋势</span><b>{{ fmtPct(analyticsStore.vm.sales.trendSlopePctPerWeek) }}/周</b></div>
          </div>

          <div class="history__cards">
            <div class="history__card">
              <div class="history__card-hd">CN 中国</div>
              <div>销量 <b>{{ analyticsStore.vm.cn.qty }}</b> · 客户 <b>{{ analyticsStore.vm.cn.uniqueCustomers }}</b></div>
              <div>单笔最大 <b>{{ analyticsStore.vm.cn.maxSingleQty }}</b> · 月频 <b>{{ analyticsStore.vm.cn.avgFreqPerMonth }}</b></div>
              <div>上次 <b>{{ analyticsStore.vm.cn.lastAt ?? "—" }}</b></div>
            </div>
            <div class="history__card">
              <div class="history__card-hd">老外</div>
              <div>销量 <b>{{ analyticsStore.vm.fo.qty }}</b> · 客户 <b>{{ analyticsStore.vm.fo.uniqueCustomers }}</b></div>
              <div>单笔最大 <b>{{ analyticsStore.vm.fo.maxSingleQty }}</b> · 月频 <b>{{ analyticsStore.vm.fo.avgFreqPerMonth }}</b></div>
              <div>上次 <b>{{ analyticsStore.vm.fo.lastAt ?? "—" }}</b></div>
            </div>
          </div>

          <div class="history__sec-hd">采购面</div>
          <div class="history__metrics">
            <div class="history__kv"><span>库存推算</span><b>{{ analyticsStore.vm.purchase.stockBalance }}</b></div>
            <div class="history__kv"><span>毛利率</span><b>{{ fmtPct(analyticsStore.vm.purchase.avgMarginPct) }}</b></div>
            <div class="history__kv"><span>365 天采购</span><b>{{ analyticsStore.vm.purchase.purchaseFreq365d }}</b></div>
            <div class="history__kv"><span>上次采购</span><b>{{ dayN(analyticsStore.vm.purchase.lastPurchaseDaysAgo) }}</b></div>
          </div>
        </template>
      </section>

      <!-- 2b: extras 深度分析 + 补货快照 -->
      <section class="history__extras-section">
        <p v-if="extrasStore.loading" class="history__msg">深度分析加载中…</p>
        <p v-else-if="extrasStore.error" class="history__error history__error--2b">深度分析加载失败：{{ extrasStore.error }}</p>
        <template v-else-if="extrasStore.vm">

          <!-- Extras Panel -->
          <div class="history__panel history__panel--extras">
            <div class="history__sec-hd">深度分析</div>

            <!-- 1. 退货率 + 价格波动 -->
            <div class="ext-section">
              <div class="ext-section-label">退货率 + 价格波动</div>
              <div class="cur-kv">
                <span class="cur-kv-label">退货率</span>
                <span class="cur-kv-val cur-kv-val--mono">
                  {{ extrasStore.vm.extras.returnRatePct != null ? extrasStore.vm.extras.returnRatePct + '%' : '—' }}
                  <span class="ext-muted">({{ extrasStore.vm.extras.returnQty }}/{{ extrasStore.vm.extras.totalSaleQtyGross + extrasStore.vm.extras.returnQty }})</span>
                </span>
              </div>
              <div class="cur-kv">
                <span class="cur-kv-label">批发售价均</span>
                <span class="cur-kv-val cur-kv-val--mono">
                  {{ extrasStore.vm.extras.priceStats.mean != null ? '€' + extrasStore.vm.extras.priceStats.mean : '—' }}
                  ±{{ extrasStore.vm.extras.priceStats.std ?? '—' }}
                </span>
              </div>
              <div class="cur-kv">
                <span class="cur-kv-label">售价区间</span>
                <span class="cur-kv-val cur-kv-val--mono">
                  {{ extrasStore.vm.extras.priceStats.min != null ? '€' + extrasStore.vm.extras.priceStats.min : '—' }}
                  ~
                  {{ extrasStore.vm.extras.priceStats.max != null ? '€' + extrasStore.vm.extras.priceStats.max : '—' }}
                </span>
              </div>
            </div>

            <!-- 2. 零售汇总 -->
            <div class="ext-section">
              <div class="ext-section-label">零售汇总 (MB700 + ID=0)</div>
              <template v-if="extrasStore.vm.extras.retailSummary.nTransactions > 0">
                <div class="cur-kv">
                  <span class="cur-kv-label">件数 / 营收</span>
                  <span class="cur-kv-val cur-kv-val--mono">{{ extrasStore.vm.extras.retailSummary.qty }} · €{{ extrasStore.vm.extras.retailSummary.revenue }}</span>
                </div>
                <div class="cur-kv">
                  <span class="cur-kv-label">笔数 / 件均</span>
                  <span class="cur-kv-val cur-kv-val--mono">{{ extrasStore.vm.extras.retailSummary.nTransactions }}笔 · {{ extrasStore.vm.extras.retailSummary.avgTicketQty ?? '—' }}</span>
                </div>
                <div class="cur-kv">
                  <span class="cur-kv-label">最近零售</span>
                  <span class="cur-kv-val cur-kv-val--mono">{{ extrasStore.vm.extras.retailSummary.lastAt ?? '—' }}</span>
                </div>
              </template>
              <div v-else class="ext-muted">暂无零售记录 (MB700 / ID=0)</div>
            </div>

            <!-- 3. CN 客户 TOP -->
            <div class="ext-section">
              <div class="ext-section-label">CN 中国客户 TOP</div>
              <table class="ext-mini-tbl">
                <thead><tr><th>ID</th><th>名字</th><th class="r">件</th><th class="r">上次</th></tr></thead>
                <tbody>
                  <template v-if="extrasStore.vm.extras.topCustomersCn.length">
                    <tr v-for="(c, i) in extrasStore.vm.extras.topCustomersCn" :key="i">
                      <td>{{ c.customerId ?? '' }}</td>
                      <td>{{ c.customerName ?? '—' }}</td>
                      <td class="r">{{ c.qty }}</td>
                      <td class="r">{{ c.lastAt ?? '' }}</td>
                    </tr>
                  </template>
                  <tr v-else><td colspan="4" class="ext-muted">—</td></tr>
                </tbody>
              </table>
            </div>

            <!-- 4. 老外客户 TOP -->
            <div class="ext-section">
              <div class="ext-section-label">老外客户 TOP</div>
              <table class="ext-mini-tbl">
                <thead><tr><th>ID</th><th>名字</th><th class="r">件</th><th class="r">上次</th></tr></thead>
                <tbody>
                  <template v-if="extrasStore.vm.extras.topCustomersForeign.length">
                    <tr v-for="(c, i) in extrasStore.vm.extras.topCustomersForeign" :key="i">
                      <td>{{ c.customerId ?? '' }}</td>
                      <td>{{ c.customerName ?? '—' }}</td>
                      <td class="r">{{ c.qty }}</td>
                      <td class="r">{{ c.lastAt ?? '' }}</td>
                    </tr>
                  </template>
                  <tr v-else><td colspan="4" class="ext-muted">—</td></tr>
                </tbody>
              </table>
            </div>

            <!-- 5. 月度热力图 -->
            <div class="ext-section">
              <div class="ext-section-label">🌡 月度热力图</div>
              <table class="heat-mini">
                <thead>
                  <tr>
                    <th></th>
                    <th v-for="m in 12" :key="m">{{ m }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="yr in extrasStore.vm.heatmap.years.slice().reverse()" :key="yr">
                    <td class="hy">{{ String(yr).slice(2) }}</td>
                    <td
                      v-for="(qty, mi) in (extrasStore.vm.heatmap.matrix[yr] || new Array(12).fill(0))"
                      :key="mi"
                      :class="isPeak(qty, extrasStore.vm.heatmap.maxQty) ? 'hc hc--peak' : 'hc'"
                      :style="(qty > 0 && !isPeak(qty, extrasStore.vm.heatmap.maxQty))
                        ? { background: `color-mix(in srgb, var(--success) ${(heatIntensity(qty, extrasStore.vm.heatmap.maxQty) * 100).toFixed(0)}%, transparent)`, color: 'var(--ink-0)' }
                        : {}"
                      :title="`${yr}-${String(mi + 1).padStart(2, '0')}: ${qty} 件`"
                    >{{ qty > 0 ? qty : '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- 6. 持仓 / 预测 / 数据范围 -->
            <div class="ext-section">
              <div class="ext-section-label">🔮 持仓 / 预测</div>
              <div v-if="extrasStore.vm.holding.avgDays != null" class="cur-kv">
                <span class="cur-kv-label">平均持仓</span>
                <span class="cur-kv-val cur-kv-val--mono">{{ extrasStore.vm.holding.avgDays }}天 <span class="ext-muted">({{ extrasStore.vm.holding.nPairs }}件)</span></span>
              </div>
              <div v-if="extrasStore.vm.holding.oldestHeldDays != null" class="cur-kv">
                <span class="cur-kv-label">当前压最久</span>
                <span class="cur-kv-val cur-kv-val--mono">{{ extrasStore.vm.holding.oldestHeldDays }}天</span>
              </div>
              <div class="cur-kv">
                <span class="cur-kv-label">预测</span>
                <span class="cur-kv-val cur-kv-val--mono" v-if="extrasStore.vm.forecast === null">
                  <span class="ext-muted">序列太短未训出</span>
                </span>
                <span class="cur-kv-val cur-kv-val--mono" v-else>
                  下季度预测 {{ extrasStore.vm.forecast.quarterMu }} 件
                  <span class="ext-muted">(p98 {{ extrasStore.vm.forecast.quarterP98 }})</span>
                  <span v-if="extrasStore.vm.forecast.isStale" class="ext-warn ext-badge">⚠ 预测过期</span>
                  <span v-if="extrasStore.vm.forecast.stockoutWeeksExcluded > 0" class="ext-muted"> 缺货周剔除 {{ extrasStore.vm.forecast.stockoutWeeksExcluded }}</span>
                </span>
              </div>
              <div class="cur-kv">
                <span class="cur-kv-label">数据范围</span>
                <span class="cur-kv-val cur-kv-val--muted">
                  {{ extrasStore.vm.extras.firstEventAt ?? '—' }} ~ {{ extrasStore.vm.extras.lastEventAt ?? '—' }}
                  <span v-if="extrasStore.vm.extras.isHistoryTruncated" class="ext-warn">⚠ 不全</span>
                </span>
              </div>
            </div>
          </div>

          <!-- Restock Snapshot Panel (only when restock !== null) -->
          <div v-if="extrasStore.vm.restock !== null" class="history__panel history__panel--restock">
            <div class="history__sec-hd">补货快照</div>
            <div class="rst-grid">

              <!-- 💰 财务 -->
              <div class="rst-sec">
                <h4>💰 财务</h4>
                <div class="rst-row">批发 <b>{{ eur(extrasStore.vm.restock.masterSalePriceEur ?? extrasStore.vm.restock.saleNetAvg) }}</b> <span class="rst-muted">(主档)</span></div>
                <!-- 零售价行 -->
                <div class="rst-row" v-if="extrasStore.vm.restock.retailPriceObserved != null && extrasStore.vm.restock.retailPriceEstimate != null">
                  零售价 <b>{{ eur(extrasStore.vm.restock.retailPriceObserved) }}</b>
                  <span class="rst-muted">(实际 {{ extrasStore.vm.restock.retailQty26w }} 笔)</span>
                  · 估算 {{ eur(extrasStore.vm.restock.retailPriceEstimate) }} (×2)
                </div>
                <div class="rst-row" v-else-if="extrasStore.vm.restock.retailPriceObserved != null">
                  零售价 <b>{{ eur(extrasStore.vm.restock.retailPriceObserved) }}</b> <span class="rst-muted">(实际)</span>
                </div>
                <div class="rst-row" v-else-if="extrasStore.vm.restock.retailPriceEstimate != null">
                  零售价 <b>{{ eur(extrasStore.vm.restock.retailPriceEstimate) }}</b> <span class="rst-muted">(批发×2 估算)</span>
                </div>
                <div class="rst-row" v-else>零售价 —</div>
                <div class="rst-row">进价 <b>{{ eur(extrasStore.vm.restock.lastPurchaseUnitPrice ?? extrasStore.vm.restock.masterStockPriceEur) }}</b></div>
                <div class="rst-row">毛利 <b>{{ extrasStore.vm.restock.marginPct != null ? extrasStore.vm.restock.marginPct + '%' : '—' }}</b></div>
              </div>

              <!-- 📦 库存 -->
              <div class="rst-sec">
                <h4>📦 库存</h4>
                <div class="rst-row">库存 <b>{{ extrasStore.vm.restock.qtyTotal != null ? extrasStore.vm.restock.qtyTotal + '件' : '—' }}</b></div>
                <div class="rst-row">可销额 <b>{{ eur(extrasStore.vm.restock.inventorySaleValueEur) }}</b></div>
                <div class="rst-row">成本 <b>{{ eur(extrasStore.vm.restock.inventoryCostValueEur) }}</b></div>
                <div class="rst-row">可撑 <b>{{ extrasStore.vm.restock.weeksOfCover != null ? extrasStore.vm.restock.weeksOfCover.toFixed(1) + '周' : '—' }}</b></div>
              </div>

              <!-- 💵 累计盈亏 -->
              <div class="rst-sec">
                <h4>💵 累计盈亏
                  <template v-if="extrasStore.vm.restock.realizedProfitEur == null">
                    <span class="rs-profit-badge rs-profit-badge--unknown">缺成本</span>
                  </template>
                  <template v-else-if="extrasStore.vm.restock.realizedProfitEur > 0">
                    <span class="rs-profit-badge rs-profit-badge--good">💚 已回本</span>
                  </template>
                  <template v-else-if="extrasStore.vm.restock.realizedProfitEur + (extrasStore.vm.restock.inventoryCostValueEur ?? 0) > 0">
                    <span class="rs-profit-badge rs-profit-badge--mid">🟡 压货中</span>
                  </template>
                  <template v-else>
                    <span class="rs-profit-badge rs-profit-badge--bad">🔴 账面亏损</span>
                  </template>
                </h4>
                <div class="rst-row">投入 <b>{{ eur(extrasStore.vm.restock.lifetimeInvestedEur) }}</b> <span class="rst-muted">({{ fmtNum(extrasStore.vm.restock.lifetimePurchaseQty) }}件)</span></div>
                <div class="rst-row">销售 <b>{{ fmtEurInt(extrasStore.vm.restock.lifetimeSaleRevenueEur) }}</b> <span class="rst-muted">({{ fmtNum(extrasStore.vm.restock.lifetimeSaleQty) }}件)</span></div>
                <!-- profit line -->
                <div class="rst-row" v-if="extrasStore.vm.restock.realizedProfitEur == null">
                  <span class="rst-muted">无 cost 数据</span>
                </div>
                <div class="rst-row" v-else-if="extrasStore.vm.restock.realizedProfitEur > 0">
                  实现利润 <b>+{{ fmtEurInt(extrasStore.vm.restock.realizedProfitEur) }}</b>
                </div>
                <div class="rst-row" v-else-if="extrasStore.vm.restock.realizedProfitEur + (extrasStore.vm.restock.inventoryCostValueEur ?? 0) > 0">
                  实现利润 <b>{{ fmtEurInt(extrasStore.vm.restock.realizedProfitEur) }}</b> · 库存能补 <b>{{ fmtEurInt(extrasStore.vm.restock.inventoryCostValueEur) }}</b> 回本
                </div>
                <div class="rst-row" v-else>
                  实现利润 <b>{{ fmtEurInt(extrasStore.vm.restock.realizedProfitEur) }}</b>
                  + 库存 <b>{{ fmtEurInt(extrasStore.vm.restock.inventoryCostValueEur) }}</b>
                  仍亏 <b>{{ fmtEurInt(-(extrasStore.vm.restock.realizedProfitEur! + (extrasStore.vm.restock.inventoryCostValueEur ?? 0))) }}</b>
                </div>
                <!-- cashflow -->
                <div class="rst-row" v-if="extrasStore.vm.restock.netCashflowEur != null">
                  净现金流 <b>{{ (extrasStore.vm.restock.netCashflowEur >= 0 ? '+' : '') + fmtEurInt(extrasStore.vm.restock.netCashflowEur) }}</b>
                  <span v-if="extrasStore.vm.restock.inventoryImbalancePct != null && extrasStore.vm.restock.inventoryImbalancePct > 30"
                    class="rs-trunc-warn"
                    :title="`进销库存差 ${extrasStore.vm.restock.inventoryImbalancePct}% > 30%, FIFO 可能高估`">
                    ⚠️ 不平 {{ extrasStore.vm.restock.inventoryImbalancePct }}%
                  </span>
                </div>
              </div>

              <!-- 📊 销售26周 -->
              <div class="rst-sec">
                <h4>📊 销售 26 周</h4>
                <div class="rst-row">周销 <b>{{ fmtNum2(extrasStore.vm.restock.weeklyVelocity) }} 件/周</b></div>
                <div class="rst-row">周额 <b>€{{ fmtNum2(extrasStore.vm.restock.weeklyRevenue) }}/周</b></div>
                <div class="rst-row">活跃 <b>{{ fmtNum(extrasStore.vm.restock.nActiveWeeks26w) }} 周</b></div>
                <div class="rst-row">距进货 <b>{{ extrasStore.vm.restock.lastPurchaseDaysAgo != null ? extrasStore.vm.restock.lastPurchaseDaysAgo + '天' : '—' }}</b></div>
              </div>

              <!-- 🎯 紧迫 -->
              <div class="rst-sec">
                <h4>🎯 紧迫 {{ extrasStore.vm.restock.urgencyScore ?? '—' }}</h4>
                <div class="rst-row">销额 <b>{{ extrasStore.vm.restock.urgencyBreakdown?.velocity ?? '—' }}</b>/30</div>
                <div class="rst-row">库存 <b>{{ extrasStore.vm.restock.urgencyBreakdown?.cover ?? '—' }}</b>/30<span
                    v-if="extrasStore.vm.restock.urgencyBreakdown?.demandValidity != null && extrasStore.vm.restock.urgencyBreakdown.demandValidity < 1.0"
                    class="rs-dv-tag"
                    title="长尾活跃度折扣">×{{ extrasStore.vm.restock.urgencyBreakdown.demandValidity }}</span></div>
                <div class="rst-row">距进货 <b>{{ extrasStore.vm.restock.urgencyBreakdown?.recency ?? '—' }}</b>/10<span
                    v-if="extrasStore.vm.restock.urgencyBreakdown?.demandValidity != null && extrasStore.vm.restock.urgencyBreakdown.demandValidity < 1.0"
                    class="rs-dv-tag"
                    title="长尾活跃度折扣">×{{ extrasStore.vm.restock.urgencyBreakdown.demandValidity }}</span></div>
                <div class="rst-row">毛利 <b>{{ extrasStore.vm.restock.urgencyBreakdown?.margin ?? '—' }}</b>/30</div>
              </div>

            </div>
          </div>

        </template>
      </section>

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
.history__recent { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; margin-bottom: var(--sp-4); }
.history__recent-label { font-size: var(--fs-xs); color: var(--ink-3); }
.history__recent-chip { font-size: var(--fs-sm); padding: 2px 8px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); background: transparent; color: var(--ink-1); cursor: pointer; }
.history__recent-chip:hover { background: var(--accent-subtle); }
.history__analytics { margin-bottom: var(--sp-6); }
.history__sec-hd { font-size: var(--fs-sm); color: var(--ink-2); margin: var(--sp-4) 0 var(--sp-2); }
.history__metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: var(--sp-3); margin-bottom: var(--sp-3); }
.history__kv { display: flex; flex-direction: column; gap: 2px; }
.history__kv span { font-size: var(--fs-sm); color: var(--ink-2); }
.history__kv b { font-family: var(--mono); }
.history__cards { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--sp-3); margin-bottom: var(--sp-3); }
.history__card { border: 1px solid var(--line-soft); border-radius: var(--r-sm); padding: var(--sp-3); font-size: var(--fs-sm); }
.history__card-hd { color: var(--ink-2); margin-bottom: var(--sp-1); }

/* 2b extras + restock panels */
.history__extras-section { margin-bottom: var(--sp-6); }
.history__panel { border: 1px solid var(--line-soft); border-radius: var(--r-sm); padding: var(--sp-4); margin-bottom: var(--sp-4); }

/* ext-section (replicate old CSS classes in scoped context) */
.ext-section { margin-bottom: var(--sp-3); }
.ext-section-label { font-size: var(--fs-sm); color: var(--ink-2); font-weight: 600; margin-bottom: var(--sp-1); }
.ext-muted { color: var(--ink-3); font-size: var(--fs-sm); }
.ext-warn { color: var(--warn); font-size: var(--fs-sm); }
.ext-badge { display: inline-block; padding: 1px 6px; border: 1px solid var(--warn); border-radius: var(--r-sm); margin-left: var(--sp-1); }

/* cur-kv rows */
.cur-kv { display: flex; gap: var(--sp-3); font-size: var(--fs-sm); margin-bottom: 2px; }
.cur-kv-label { color: var(--ink-2); min-width: 80px; }
.cur-kv-val { font-family: var(--mono); }
.cur-kv-val--muted { color: var(--ink-2); }

/* ext-mini-tbl */
.ext-mini-tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.ext-mini-tbl th, .ext-mini-tbl td { padding: 2px var(--sp-2); border-bottom: 1px solid var(--line-soft); text-align: left; }
.ext-mini-tbl .r { text-align: right; }
.ext-mini-tbl .id { font-family: var(--mono); }

/* heat-mini */
.heat-mini { border-collapse: collapse; font-size: var(--fs-xs); }
.heat-mini th, .heat-mini td { padding: 2px 4px; text-align: center; border: 1px solid var(--line-soft); }
.hc { color: var(--ink-3); }
.hc--peak { background: var(--accent); color: var(--ink-0); font-weight: 700; }
.hy { color: var(--ink-2); font-family: var(--mono); }

/* rst-grid (restock snapshot) */
.rst-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--sp-3); }
.rst-sec { font-size: var(--fs-sm); }
.rst-sec h4 { font-size: var(--fs-sm); color: var(--ink-1); margin: 0 0 var(--sp-2); display: flex; align-items: center; gap: var(--sp-1); flex-wrap: wrap; }
.rst-row { margin-bottom: 2px; color: var(--ink-1); }
.rst-muted { color: var(--ink-3); }
.rs-trunc-warn { color: var(--warn); font-size: var(--fs-xs); }

/* profit badges */
.rs-profit-badge { font-size: var(--fs-xs); padding: 1px 5px; border-radius: var(--r-sm); }
.rs-profit-badge--unknown { background: var(--ink-3); color: var(--ink-0); }
.rs-profit-badge--good { background: var(--accent-subtle); color: var(--accent); }
.rs-profit-badge--mid { background: var(--warn-subtle); color: var(--warn); }
.rs-profit-badge--bad { color: var(--error); border: 1px solid var(--error); }

/* demand_validity discount tag (×dv) */
.rs-dv-tag { font-size: var(--fs-xs); color: var(--ink-2); margin-left: 3px; }
</style>
