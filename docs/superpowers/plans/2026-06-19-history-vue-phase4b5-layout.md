# 货号历史 Phase 4b.5（信息架构重排）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `frontend/src/pages/history/HistoryPage.vue` 货号查询 tab 命中态从扁平单列重排为「左固定 340 概况/深度 + 右弹性 5 折叠卡」，对齐旧 Alpine 页信息架构。

**Architecture:** 纯前端模板 + scoped CSS 重排，零业务/数据逻辑变更。复用现有 `history`/`skuAnalytics`/`skuExtras`/`skuTimeline` store、`TimelineChart.vue`、`tokens.css`，全不动。生产代码只改 `HistoryPage.vue`（新增 `leftTab`+`cardOpen` 两个 UI state、换 SKU 重置 watcher、两栏模板、折叠卡模板/CSS 模式）。容器查询（非视口媒体查询）控制 >900/≤900 响应式。

**Tech Stack:** Vue 3 `<script setup>` + TypeScript + Pinia + Vitest + @vue/test-utils。

**设计 spec：** `docs/superpowers/specs/2026-06-19-history-vue-phase4b5-layout-design.md`（终审 APPROVE）。

---

## 文件结构

- Modify: `frontend/src/pages/history/HistoryPage.vue`（生产代码，唯一）
- Modify: `frontend/src/pages/history/HistoryPage.test.ts`（替换过时断言 + 新增）

> 前端命令全部在 `frontend/` 目录跑（仓库根无 package.json）。Vitest = `npm run test -- <pattern>`。

### 命中态目标结构（Task 2 落地）

```
<template v-else-if="store.result.kind === 'hit'">
  <div class="history__cols">
    <aside class="history__left">
      [Hero]                         ← 现 180-188 verbatim
      [概况/深度 tab 按钮]            ← 新增
      <div v-show="leftTab==='overview'"> [overview dl] </div>   ← 现 190-199 verbatim
      <div v-show="leftTab==='deep'">  [深度: extras loading/error/vm-null 守卫 + extras panel] </div>  ← 现 254-405
    </aside>
    <div class="history__right">
      [SLA 卡]  ← analytics loading/error/vm 守卫 + 现 218-240
      [PUR 卡]  ← analytics loading/error/vm 守卫 + 现 242-248
      [RST 卡]  ← extras loading/error/vm-null/restock-null 守卫 + 现 408-511
      [TML 卡]  ← 现 202-211
      [HIS 卡]  ← 现 516-536
    </div>
  </div>
</template>
```

非命中态分支（notfound/fuzzy/初始/加载/错误，现 ~130-177）与批次记录 tab（现 540-547）**不动**。

---

## Task 1: UI 状态 + 换 SKU 重置（TDD）

**Files:**
- Modify: `frontend/src/pages/history/HistoryPage.vue`（`<script setup>` 顶部，现有 ref 声明附近）
- Test: `frontend/src/pages/history/HistoryPage.test.ts`

> 本任务只加 script 状态 + 在命中态模板里加最小可测的钩子（tab 按钮 + 一张可折叠卡的壳），让行为测试能跑。完整两栏重排在 Task 2。为避免 Task 1 与 Task 2 的模板冲突，本任务**只加 script，不改模板**；行为测试通过"直接读组件暴露的状态"不可行（`<script setup>` 不暴露内部），故 Task 1 的测试改为在 Task 2 模板就绪后一起验证。**Task 1 仅落 script 状态 + 提交**，测试断言随 Task 2/4。

- [ ] **Step 1: 加 script 状态**

在 `HistoryPage.vue` 的 `<script setup>` 中，`const q = ref("")` 之后、`activeTab` 声明附近加：

```typescript
import { computed, watch } from "vue"; // 若已 import ref，补 computed/watch（检查现有 import 行合并，勿重复声明）

// Phase 4b.5: 左栏 概况/深度 + 右栏折叠卡 UI 状态
const leftTab = ref<"overview" | "deep">("overview");
const DEFAULT_CARD_OPEN = { sla: true, pur: true, rst: false, tml: false, his: false } as const;
type CardKey = keyof typeof DEFAULT_CARD_OPEN;
const cardOpen = ref<Record<CardKey, boolean>>({ ...DEFAULT_CARD_OPEN });
function toggleCard(k: CardKey) { cardOpen.value[k] = !cardOpen.value[k]; }

// 换 SKU（命中新 barcode）→ 重置左 tab + 折叠态，防 SKU A 状态泄漏到 B
const hitBarcode = computed(() =>
  store.result?.kind === "hit" ? store.result.current.barcode : null);
watch(hitBarcode, (bc) => {
  if (bc) { leftTab.value = "overview"; cardOpen.value = { ...DEFAULT_CARD_OPEN }; }
});
```

> 注意：`HistoryPage.vue` 顶部已有 `import { ref } from "vue"`（见现有第 2 行附近）。把 `computed, watch` 合并进该行（`import { ref, computed, watch } from "vue"`），不要新增第二条 vue import。

- [ ] **Step 2: 类型检查通过**

Run（`frontend/`）: `npm run build`
Expected: clean（vue-tsc 无未用变量错误前提是 Task 2 会用到 leftTab/cardOpen/toggleCard；若 vue-tsc 因"声明未使用"报错，本任务可暂时在模板加一处 `v-if="false"` 引用，或直接连做 Task 2。推荐：Task 1+2 连续实施，中间不单独 build。）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/history/HistoryPage.vue
git commit -m "feat(history): Phase 4b.5 左tab+折叠卡 UI 状态 + 换 SKU 重置 watcher"
```

---

## Task 2: 命中态两栏 + 折叠卡模板重排

**Files:**
- Modify: `frontend/src/pages/history/HistoryPage.vue`（替换命中态分支 `<template v-else-if="store.result.kind === 'hit'">` … `</template>`，现 179-537）

**核心做法**：现有内部块（Hero/overview/SLA metrics/PUR metrics/extras panel/restock panel/timeline-chart/history timeline）**内容 verbatim 保留**，只改它们的**外层包裹与位置**，并给每张卡补 store 守卫。下面给出完整新骨架，标注每处嵌入哪段现有块。

- [ ] **Step 1: 替换命中态分支为新骨架**

把现 179-537 行整段 `<template v-else-if="store.result.kind === 'hit'"> … </template>` 替换为：

```vue
    <template v-else-if="store.result.kind === 'hit'">
      <div class="history__cols">
        <!-- ===== 左栏：Hero + 概况/深度 ===== -->
        <aside class="history__left">
          <!-- Hero：保留现 180-188 整块 verbatim -->
          <div class="history__hero">
            <span class="history__model">{{ store.result.current.model || "—" }}</span>
            <span class="history__barcode">{{ store.result.current.barcode }}</span>
            <span class="history__pill" :class="store.result.current.isTrulyDiscontinued ? 'is-off' : 'is-on'">
              {{ store.result.current.isTrulyDiscontinued ? "已停售" : "在售" }}
            </span>
            <span v-if="store.result.current.manualGrade !== null" class="history__grade">{{ store.result.current.manualGrade }}</span>
            <button class="history__btn history__btn--ghost" type="button" @click="copyBarcode(store.result.current.barcode)">⎘ 复制</button>
          </div>

          <!-- 概况/深度 切换（普通按钮 + aria-pressed，非 tablist） -->
          <div class="history__lefttabs">
            <button type="button" class="history__lefttab" :class="{ 'is-active': leftTab === 'overview' }"
              :aria-pressed="leftTab === 'overview'" @click="leftTab = 'overview'">概况</button>
            <button type="button" class="history__lefttab" :class="{ 'is-active': leftTab === 'deep' }"
              :aria-pressed="leftTab === 'deep'" @click="leftTab = 'deep'">深度</button>
          </div>

          <!-- 概况：保留现 190-199 的 <dl class="history__overview"> 整块 verbatim -->
          <dl v-show="leftTab === 'overview'" class="history__overview">
            <template v-if="store.result.current.productNameZh"><dt>品名</dt><dd>{{ store.result.current.productNameZh }}</dd></template>
            <template v-if="store.result.current.productNameLocal"><dt>本地品名</dt><dd>{{ store.result.current.productNameLocal }}</dd></template>
            <dt>店面位置</dt><dd>{{ store.result.current.storeLocations.join(", ") || "—" }}</dd>
            <dt>仓库位置</dt><dd>{{ store.result.current.warehouseLocations.join(", ") || "—" }}</dd>
            <template v-if="store.result.current.unknownLocations.length"><dt>其他位置</dt><dd>{{ store.result.current.unknownLocations.join(", ") }}</dd></template>
            <template v-if="store.result.current.salePrice !== null"><dt>售价</dt><dd>€{{ store.result.current.salePrice.toFixed(2) }}</dd></template>
            <dt>来源</dt><dd>{{ cn(SOURCE_CN, store.result.current.source) || "—" }}</dd>
            <dt>最后更新</dt><dd>{{ store.result.current.updatedAt ?? "—" }}</dd>
          </dl>

          <!-- 深度：extras 守卫链（loading→error→vm-null→内容） -->
          <div v-show="leftTab === 'deep'" class="history__deep">
            <p v-if="extrasStore.loading" class="history__msg">深度分析加载中…</p>
            <p v-else-if="extrasStore.error" class="history__error history__error--2b">深度分析加载失败：{{ extrasStore.error }}</p>
            <p v-else-if="!extrasStore.vm" class="history__msg">暂无深度数据</p>
            <div v-else class="history__panel history__panel--extras">
              <!-- 保留现 260-405 的 extras panel 内部（深度分析 sec-hd + 退货率/零售/客户TOP/热力图/持仓预测各 ext-section）verbatim。
                   注意：原 259 行的外层 <div class="history__panel--extras"> 已由本 v-else 提供，勿重复包裹。 -->
              <div class="history__sec-hd">深度分析</div>
              <!-- … 现 262-404 的全部 ext-section 块原样粘入 … -->
            </div>
          </div>
        </aside>

        <!-- ===== 右栏：5 张折叠卡 ===== -->
        <div class="history__right">
          <!-- SLA 销售分析 -->
          <section class="history__card">
            <button type="button" class="history__card-hd" id="sbcard-sla" aria-controls="sbpanel-sla"
              :aria-expanded="cardOpen.sla" @click="toggleCard('sla')">
              <span class="history__card-badge">SLA</span> 销售分析
              <span class="history__card-chevron">{{ cardOpen.sla ? '▼' : '▶' }}</span>
            </button>
            <div id="sbpanel-sla" role="region" aria-labelledby="sbcard-sla" v-show="cardOpen.sla" class="history__card-bd">
              <p v-if="analyticsStore.loading" class="history__msg">分析加载中…</p>
              <p v-else-if="analyticsStore.error" class="history__error">分析加载失败：{{ analyticsStore.error }}</p>
              <template v-else-if="analyticsStore.vm">
                <!-- 保留现 219-240：销售分析 metrics + 客户拆分 cards verbatim（去掉原 218 的 sec-hd「销售分析」，标题已在卡头） -->
                <div class="history__metrics"> … 现 219-225 … </div>
                <div class="history__cards"> … 现 227-240 … </div>
              </template>
            </div>
          </section>

          <!-- PUR 采购面 -->
          <section class="history__card">
            <button type="button" class="history__card-hd" id="sbcard-pur" aria-controls="sbpanel-pur"
              :aria-expanded="cardOpen.pur" @click="toggleCard('pur')">
              <span class="history__card-badge">PUR</span> 采购面
              <span class="history__card-chevron">{{ cardOpen.pur ? '▼' : '▶' }}</span>
            </button>
            <div id="sbpanel-pur" role="region" aria-labelledby="sbcard-pur" v-show="cardOpen.pur" class="history__card-bd">
              <p v-if="analyticsStore.loading" class="history__msg">分析加载中…</p>
              <p v-else-if="analyticsStore.error" class="history__error">分析加载失败：{{ analyticsStore.error }}</p>
              <template v-else-if="analyticsStore.vm">
                <!-- 保留现 243-248：采购面 metrics verbatim（去掉原 242 的 sec-hd「采购面」） -->
                <div class="history__metrics"> … 现 243-248 … </div>
              </template>
            </div>
          </section>

          <!-- RST 补货决策快照 -->
          <section class="history__card">
            <button type="button" class="history__card-hd" id="sbcard-rst" aria-controls="sbpanel-rst"
              :aria-expanded="cardOpen.rst" @click="toggleCard('rst')">
              <span class="history__card-badge">RST</span> 补货决策快照
              <span class="history__card-chevron">{{ cardOpen.rst ? '▼' : '▶' }}</span>
            </button>
            <div id="sbpanel-rst" role="region" aria-labelledby="sbcard-rst" v-show="cardOpen.rst" class="history__card-bd">
              <p v-if="extrasStore.loading" class="history__msg">补货快照加载中…</p>
              <p v-else-if="extrasStore.error" class="history__error">补货快照加载失败：{{ extrasStore.error }}</p>
              <p v-else-if="!extrasStore.vm" class="history__msg">暂无补货快照</p>
              <p v-else-if="extrasStore.vm.restock === null" class="history__msg">暂无补货快照</p>
              <div v-else class="history__panel history__panel--restock">
                <!-- 保留现 410-510 的 <div class="rst-grid"> 整块 verbatim（去掉原 409 的 sec-hd「补货快照」，标题已在卡头；
                     原 408 的外层 v-if="restock!==null" 包裹由本 v-else 链替代，勿重复） -->
                <div class="rst-grid"> … 现 411-509 全部 rst-sec … </div>
              </div>
            </div>
          </section>

          <!-- TML 销售/进价时间线 -->
          <section class="history__card">
            <button type="button" class="history__card-hd" id="sbcard-tml" aria-controls="sbpanel-tml"
              :aria-expanded="cardOpen.tml" @click="toggleCard('tml')">
              <span class="history__card-badge">TML</span> 销售/进价时间线
              <span class="history__card-chevron">{{ cardOpen.tml ? '▼' : '▶' }}</span>
            </button>
            <div id="sbpanel-tml" role="region" aria-labelledby="sbcard-tml" v-show="cardOpen.tml" class="history__card-bd">
              <!-- 保留现 204-210 verbatim（去掉原 203 的 sec-hd「销售/进价走势」，标题已在卡头） -->
              <p v-if="timelineStore.loading" class="history__msg">走势图加载中…</p>
              <p v-else-if="timelineStore.error" class="history__error history__timeline-chart-error">走势图加载失败：{{ timelineStore.error }}</p>
              <TimelineChart v-else-if="timelineStore.vm" :weeks="timelineStore.vm.weeks" :monthly-sales="timelineStore.vm.monthlySales" />
            </div>
          </section>

          <!-- HIS 历史时间线 -->
          <section class="history__card">
            <button type="button" class="history__card-hd" id="sbcard-his" aria-controls="sbpanel-his"
              :aria-expanded="cardOpen.his" @click="toggleCard('his')">
              <span class="history__card-badge">HIS</span> 历史时间线
              <span class="history__card-chevron">{{ cardOpen.his ? '▼' : '▶' }}</span>
            </button>
            <div id="sbpanel-his" role="region" aria-labelledby="sbcard-his" v-show="cardOpen.his" class="history__card-bd">
              <!-- 保留现 518-535 verbatim（去掉原 517 的 timeline-hd「历史时间线」，标题已在卡头） -->
              <p v-if="!store.result.events.length" class="history__msg">暂无历史变更</p>
              <div v-else>
                <div class="history__count">共 {{ store.result.events.length }} 次操作</div>
                <div v-for="(ev, i) in store.result.events" :key="i" class="history__evt"> … 现 522-533 … </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </template>
```

> **实施要点（务必照做）：**
> - `… 现 X-Y …` 处粘入对应行区间的现有标记内 verbatim 内容（不改字段/绑定/helper 调用）。这些块用的 helper（`eur`/`fmtPct`/`dayN`/`cn`/`SOURCE_CN`/`CHANGE_TYPE_CN`/`FIELD_CN`/`fmtNum`/`fmtEurInt`/`fmtNum2`/`copyBarcode`）都在同文件 script 中，无需改 import。
> - 删除原 `<section class="history__analytics">`（213-250）、`<section class="history__extras-section">`（252-514）、`<div class="history__timeline-chart">`（201-211）、`<div class="history__timeline">`（516-536）这些**旧外层包裹**——它们的内部块已迁入新卡/左栏。
> - RST：原 408 的 `v-if="extrasStore.vm.restock !== null"` 包裹**移除**，由卡身的 `v-else-if="extrasStore.vm.restock === null"`→「暂无补货快照」+ `v-else`→内容 这条链替代。**关键防崩**：先 `!extrasStore.vm`（vm-null）分支，再 `extrasStore.vm.restock === null`，最后才解引用 `extrasStore.vm.restock.*`。
> - SLA/PUR 现在各有独立 `analyticsStore.loading/error/vm` 守卫（原来两块共享一个 section 守卫）。

- [ ] **Step 2: 类型 + 构建通过**

Run（`frontend/`）: `npm run build`
Expected: clean（无 vue-tsc 错误、无未闭合标签）。若报 `leftTab`/`cardOpen`/`toggleCard` 未使用 → 说明 Task 1 状态未正确落地或本步骤模板未引用，回查。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/history/HistoryPage.vue
git commit -m "feat(history): Phase 4b.5 命中态两栏 + 5 折叠卡重排（左概况/深度 + 右SLA/PUR/RST/TML/HIS）"
```

---

## Task 3: scoped CSS（容器查询两栏 + 折叠卡 + 溢出保护）

**Files:**
- Modify: `frontend/src/pages/history/HistoryPage.vue`（`<style scoped>`，现 551 起）

- [ ] **Step 1: 改 `.history` + 加两栏/卡片/响应式 CSS**

把现 552 行 `.history { padding: var(--sp-6); max-width: 1100px; margin: 0 auto; }` 改为（加 `container-type` + `max-width:1400px`）：

```css
.history { padding: var(--sp-6); max-width: 1400px; margin: 0 auto; container-type: inline-size; }
```

在 `<style scoped>` 内追加（放在现有规则之后）：

```css
/* Phase 4b.5: 两栏布局 */
.history__cols { display: flex; gap: var(--sp-5); align-items: flex-start; }
.history__left { flex: 0 0 340px; min-width: 0; }
.history__right { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; gap: var(--sp-4); }

/* 概况/深度 左 tab */
.history__lefttabs { display: flex; gap: var(--sp-2); margin: var(--sp-3) 0; }
.history__lefttab { padding: 4px 12px; background: transparent; border: 1px solid var(--line-soft); border-radius: var(--r-sm); color: var(--ink-2); cursor: pointer; font-size: var(--fs-sm); }
.history__lefttab.is-active { color: var(--ink-0); border-color: var(--accent); }
.history__deep { } /* 深度内容容器，沿用 ext-section 既有样式 */

/* 深度栏 TOP 表 + 热力图 横向溢出保护（340px 容不下时局部横滚） */
.history__deep table,
.history__deep .heat-table { display: block; max-width: 100%; overflow-x: auto; }

/* 折叠卡 */
.history__card { border: 1px solid var(--line-soft); border-radius: var(--r-md); overflow: hidden; }
.history__card-hd { display: flex; align-items: center; gap: var(--sp-2); width: 100%; padding: var(--sp-3) var(--sp-4); background: var(--surface-1, transparent); border: none; color: var(--ink-0); cursor: pointer; text-align: left; font-size: var(--fs-sm); }
.history__card-badge { font-size: 11px; padding: 1px 6px; border: 1px solid var(--line-soft); border-radius: var(--r-sm); color: var(--ink-2); }
.history__card-chevron { margin-left: auto; color: var(--ink-3); }
.history__card-bd { padding: var(--sp-3) var(--sp-4); border-top: 1px solid var(--line-soft); }

/* 容器查询：内容宽 ≤900 堆叠（900 归堆叠侧），>900 两栏 */
@container (max-width: 900px) {
  .history__cols { flex-direction: column; }
  .history__left { flex-basis: auto; width: 100%; }
}
```

> `var(--surface-1, transparent)` 用带兜底的写法（项目 token 表若无 `--surface-1` 则回退 transparent，避免重蹈 Task 6 的未定义 token 坑）。删除/保留旧 `.history__analytics`/`.history__extras-section`/`.history__timeline-chart`/`.history__timeline` 等仅外层布局相关的样式按需清理（内部 `.history__metrics`/`.history__kv`/`.history__card`(旧客户卡，注意与新 `.history__card` 折叠卡命名冲突！见下) 等保留）。

- [ ] **Step 2: 处理命名冲突 `.history__card`**

⚠️ 现有 219-240 的客户拆分卡已用 class `.history__card`（见现 228/234）。本计划新折叠卡也想叫 `.history__card`。**冲突**。解决：折叠卡 class 改用 **`.history__foldcard`**（卡头 `.history__foldcard-hd` / 卡身 `.history__foldcard-bd` / 徽标 `.history__foldcard-badge` / chevron `.history__foldcard-chevron`），全程替换 Task 2 模板与本 Task CSS 中的 `history__card*`（折叠卡相关）为 `history__foldcard*`。客户拆分旧卡 `.history__card` 保持不变。

Run（`frontend/`）: `npm run build`
Expected: clean。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/history/HistoryPage.vue
git commit -m "feat(history): Phase 4b.5 两栏/折叠卡 scoped CSS（容器查询 >900/≤900 + min-width:0 + 溢出保护 + max-width 1400）"
```

---

## Task 4: 测试更新 + 回归

**Files:**
- Modify: `frontend/src/pages/history/HistoryPage.test.ts`

> 先读该文件了解既有 mount 工具 / store stub 约定（它用 plain object stub store + 注入 state，见现有 `reset()`/`hitState()`/`aExtrasVm()`/`aRestock()` helper）。沿用其约定。下面断言里的选择器对应 Task 2/3 的 `history__foldcard*` 命名与 `history__cols`。

- [ ] **Step 1: 替换过时断言**

1. 旧测试 `it("P3: 顺序 — 概况 dl 在走势图块之前，走势图块在销售分析之前", …)`（断言旧单列顺序）→ **替换**为右栏卡片顺序断言：

```typescript
it("4b.5: 命中态渲染两栏；右栏卡片顺序 SLA→PUR→RST→TML→HIS", () => {
  reset(); hitState();
  const w = mount(HistoryPage);
  expect(w.find(".history__cols").exists()).toBe(true);
  const badges = w.findAll(".history__foldcard-badge").map((b) => b.text());
  expect(badges).toEqual(["SLA", "PUR", "RST", "TML", "HIS"]);
});
```

2. 旧测试 `it("2b: restock null → 不渲染补货快照面板", …)`（断言 restock=null 时无「补货快照」）→ **替换**为新空态：

```typescript
it("4b.5: restock null → RST 卡在且卡身显示「暂无补货快照」", () => {
  reset(); hitState(); extrasState.vm = aExtrasVm(null);
  const w = mount(HistoryPage);
  const rst = w.find("#sbpanel-rst");
  expect(rst.exists()).toBe(true);
  // RST 默认折叠，断言内容文本即可（v-show 仍在 DOM）
  expect(rst.text()).toContain("暂无补货快照");
});
```

- [ ] **Step 2: 跑这两条确认通过**

Run（`frontend/`）: `npm run test -- HistoryPage`
Expected: 这两条 PASS（其余可能因模板改动需后续步骤调整，先确认这两条对齐新结构）。

- [ ] **Step 3: 加新行为测试**

在 `HistoryPage.test.ts` 追加：

```typescript
it("4b.5: 概况/深度 切换换左栏内容且不影响右卡", async () => {
  reset(); hitState(); extrasState.vm = aExtrasVm(aRestock());
  const w = mount(HistoryPage);
  const tabs = w.findAll(".history__lefttab");
  const deepBtn = tabs.find((b) => b.text() === "深度")!;
  // 默认概况：overview dl 可见，深度不可见
  expect(w.find(".history__overview").isVisible()).toBe(true);
  expect(w.find(".history__deep").isVisible()).toBe(false);
  await deepBtn.trigger("click");
  expect(deepBtn.attributes("aria-pressed")).toBe("true");
  expect(w.find(".history__overview").isVisible()).toBe(false);
  expect(w.find(".history__deep").isVisible()).toBe(true);
  // 右卡不受左 tab 影响：SLA 卡身仍可见（默认开）
  expect(w.find("#sbpanel-sla").isVisible()).toBe(true);
});

it("4b.5: 默认折叠态 SLA/PUR 开、RST/TML/HIS 关（用 isVisible 非文本）", () => {
  reset(); hitState(); extrasState.vm = aExtrasVm(aRestock());
  const w = mount(HistoryPage);
  expect(w.find("#sbpanel-sla").isVisible()).toBe(true);
  expect(w.find("#sbpanel-pur").isVisible()).toBe(true);
  expect(w.find("#sbpanel-rst").isVisible()).toBe(false);
  expect(w.find("#sbpanel-tml").isVisible()).toBe(false);
  expect(w.find("#sbpanel-his").isVisible()).toBe(false);
});

it("4b.5: 折叠 toggle 翻转 aria-expanded 与卡身可见性", async () => {
  reset(); hitState(); extrasState.vm = aExtrasVm(aRestock());
  const w = mount(HistoryPage);
  const rstHd = w.find("#sbcard-rst");
  expect(rstHd.attributes("aria-expanded")).toBe("false");
  expect(w.find("#sbpanel-rst").isVisible()).toBe(false);
  await rstHd.trigger("click");
  expect(rstHd.attributes("aria-expanded")).toBe("true");
  expect(w.find("#sbpanel-rst").isVisible()).toBe(true);
});

it("4b.5: 换新 barcode → leftTab 回 overview、折叠态回默认", async () => {
  reset(); hitState(); extrasState.vm = aExtrasVm(aRestock());
  const w = mount(HistoryPage);
  // 切到深度 + 展开 RST
  await w.findAll(".history__lefttab").find((b) => b.text() === "深度")!.trigger("click");
  await w.find("#sbcard-rst").trigger("click");
  expect(w.find(".history__deep").isVisible()).toBe(true);
  expect(w.find("#sbpanel-rst").isVisible()).toBe(true);
  // 命中新 barcode（改 state.result.current.barcode 触发 watcher）
  state.result = { ...state.result, current: { ...state.result.current, barcode: "NEWBC999" } } as never;
  await w.vm.$nextTick();
  expect(w.find(".history__overview").isVisible()).toBe(true);  // 回概况
  expect(w.find("#sbpanel-rst").isVisible()).toBe(false);        // RST 回折叠
});

it("4b.5: extras vm=null（401 后）→ RST 卡与深度栏不崩、显占位", () => {
  reset(); hitState(); extrasState.vm = null; // loading=false/error=null/vm=null
  expect(() => mount(HistoryPage)).not.toThrow();
  const w = mount(HistoryPage);
  expect(w.find("#sbpanel-rst").text()).toContain("暂无补货快照");
});

it("4b.5: analytics error → SLA 与 PUR 两卡各显错误条", () => {
  reset(); hitState(); analyticsState.error = "boom"; analyticsState.vm = null;
  const w = mount(HistoryPage);
  expect(w.find("#sbpanel-sla").text()).toContain("boom");
  expect(w.find("#sbpanel-pur").text()).toContain("boom");
});
```

> 上面 `state` / `analyticsState` / `extrasState` / `hitState()` / `aExtrasVm()` / `aRestock()` 是该测试文件**既有** helper/响应式 stub（实施时按文件实际命名对齐；若 analytics stub 名不同，照该文件现有 analytics store stub 写法设 error/vm）。`aExtrasVm(null)` 既有用法 = restock 为 null 的 extras vm（见旧 "2b: restock null" 测试）。vm=null 用例需要把整个 extras vm 设为 null（非 `aExtrasVm(null)`）——按文件 stub 结构设 `extrasState.vm = null`。

- [ ] **Step 4: 跑全文件确认通过**

Run（`frontend/`）: `npm run test -- HistoryPage`
Expected: 全 PASS（新 6 条 + 改写 2 条 + 既有未受影响的）。

- [ ] **Step 5: 全量前端回归 + 构建**

Run（`frontend/`）: `npm run test` 然后 `npm run build`
Expected: 全绿（重排不改数据流，7 状态/RECENT/批次子-tab/no-analytics/预测过期徽标等既有测试继续过）；build clean。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/history/HistoryPage.test.ts
git commit -m "test(history): Phase 4b.5 两栏/折叠/换SKU重置/vm-null防崩/共享错误态 + 替换过时单列断言"
```

---

## Task 5: 浏览器人工验收 + 收尾

- [ ] **Step 1: 本地起前端，对照两档宽度**

Run: `./dev.ps1 -Frontend`（:5173），浏览器开 `/ui/history` 查一个有完整数据的货号。
- 宽窗口（内容 >900px）：两栏，左 340 概况/深度 + 右 5 卡；切深度看热力图/客户表不撑破（横向局部可滚）；折叠卡点开/收起正常。
- 窄窗口（拖窄到内容 ≤900px，含 App Shell 侧栏占用）：堆叠，左栏置顶、卡片在下；**断言无横向滚动条**。
- 与旧 `/?page=history`（同浏览器另开）并排对照信息架构是否对齐。

- [ ] **Step 2: 用户视觉验收**

请用户确认视觉够格。够格 → 才进 Phase 4c 退役旧页（另起）。

- [ ] **Step 3: 收尾**

按 `superpowers:finishing-a-development-branch`：push `feat/history-vue-phase4b5` → PR → 独立等 CI 全绿 → squash merge。

---

## Self-Review 笔记

- **Spec 覆盖**：两栏容器查询(T3) / max-width 1400(T3) / 左栏固定 340 + min-width:0(T3) / Hero+概况/深度 按钮 aria-pressed(T2) / 深度 extras vm-null 守卫 + 溢出保护(T2/T3) / 5 折叠卡顺序+默认态(T2/T4) / SLA·PUR 共享 analytics 错误态(T2/T4) / RST extras loading·error·vm-null·restock-null 链(T2/T4) / TML v-show(T2) / 卡头 id+aria-controls+卡身 aria-labelledby(T2) / 换 SKU 重置(T1/T4) / 替换旧单列&restock-null 断言(T4) / 折叠用 isVisible(T4) / 响应式人工验收(T5) / 回归(T4)。全覆盖。
- **命名冲突**：旧 `.history__card`（客户拆分卡）与折叠卡冲突 → 折叠卡统一用 `.history__foldcard*`（T3 Step2 显式处理，T2 模板与 T4 选择器同步）。
- **防崩不变量**：RST 与深度栏所有 `extrasStore.vm.*` 访问均在 `!extrasStore.vm` 守卫之后（T2 要点 + T4 vm-null 用例钉死）。
- **无占位**：除「… 现 X-Y verbatim …」的既有块迁移引用（内容不变、避免转录错误）外，所有新增 script/模板骨架/CSS/测试均为完整代码。
- **类型一致**：`leftTab`/`cardOpen`/`CardKey`/`toggleCard`/`DEFAULT_CARD_OPEN`(T1) 在 T2 模板、T4 测试一致引用；选择器 `history__cols`/`history__foldcard*`/`#sbpanel-*`/`#sbcard-*`/`history__lefttab`/`history__overview`/`history__deep` 跨 T2/T3/T4 一致。
