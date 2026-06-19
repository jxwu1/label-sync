# 货号历史页迁移 Vue —— Phase 4b（批次记录 tab：扫描批次）设计

**状态：** 设计待批（2026-06-19）。已吸收两轮审查。
第一轮：CSV 元数据 nullable（BLOCKER）、ZIP 改 additive 增强而非 1:1（MEDIUM）、下载 URL 强制编码（HIGH）、子-tab `scanVisited` 持久挂载、多行独立展开、employees 口径从返回批次派生（MEDIUM）。
第二轮：`API_MODELS` 追加 `ScanBatchList` + 断言 TS 类型生成（BLOCKER 类型静默缺失）、ZIP 下载端到端路由测试（BLOCKER）、重试统一走 `ensureLoaded`、CSV「不可读」收窄为 OSError 并标注 UnicodeDecodeError 潜在风险、折叠头 `<button aria-expanded>`、`onMounted→ensureLoaded` 测试。

## 目标

给 `/ui/history` 的「批次记录」tab 加一个子-tab：**最近改动**（Phase 4a 已上线）↔ **扫描批次**。迁移旧 `index-scan-history.js` 的扫描批次浏览/下载能力。列表走**新建 strict `/api/` 端点**；二进制下载**复用既有 `/scan_history/*` 端点**。

仍 **additive**：旧 SPA 扫描历史页（`/?page=...`）、旧 `/scan_history/*` 全部端点（列表 + 下载）一律保留不动。

货号历史 4 阶段已完成 P1/2a/2b/3（查询 tab 全部内容）+ 4a（批次记录 tab 的「最近改动」子面板）。本期 = 批次记录 tab 的「扫描批次」子面板。**Phase 4c** 统一退役旧页 + 旧 `/recent_changes/*` + 旧 `/scan_history/*` + 删「旧版」深链。

## 范围

### 做（Phase 4b）

- 批次记录 tab 内加一级子-tab：**最近改动**（现 4a 内容）↔ **扫描批次**。默认「最近改动」。「扫描批次」子-tab 首次激活 lazy 加载。
- 扫描批次子面板（`ScanBatchPanel.vue`），复刻旧 `index-scan-history.js`：
  - 员工筛选下拉（含首项「全部员工」）→ 客户端筛选。
  - 可折叠批次行：行头用 `<button type="button" :aria-expanded>`（语义化、键盘可达，非裸 div onclick），内容 = 扫描时间 / 员工 / 摘要（`{N} 行 · {M} 个 xlsx` 或「无 CSV」）+ chevron；展开后 = CSV 行 + 各 XLSX 行 + 下载链接。**多行可同时独立展开**（逐行 toggle）。
  - CSV 缺失时显示「📄 CSV 缺失」灰字（无下载链接），与旧版一致。
- 新建 1 个 strict `/api/history/scan-batches` 列表端点（pydantic `extra=forbid`）。
- **下载链接复用既有端点**：`/scan_history/batches/{batch_id}/download/csv` 与 `/scan_history/batches/{batch_id}/files/{filename}`。
- **additive 增强**：每个批次额外加「下载全部 ZIP」链接，复用既有 `/scan_history/batches/{batch_id}/download/zip`。旧前端没有 ZIP 链接，本期明确补上（非 1:1，是有意增强）。

### 不做（YAGNI / 留后续）

- 不删旧端点 / 旧页 / 「旧版」深链 → Phase 4c。
- 不动旧 SPA / 旧 `/scan_history/*` 端点实现（仅复用）。
- 无行下钻（扫描批次只下载文件，不切回查询 tab）。
- 列表 ≤100 批次（沿用旧 `limit=100`），不分页、不加 RENDER_CAP。
- 不重构最近改动子面板，不引表格库。

## 与 1:1 复刻的明确偏差（验收对照）

| 项 | 旧 `index-scan-history.js` | Phase 4b | 性质 |
|---|---|---|---|
| CSV / XLSX 下载 | 有 | 有（行为一致） | 1:1 |
| ZIP「下载全部」 | **无** | **有** | additive 增强 |
| 员工下拉来源 | 后端 `employees`（扫**全部目录**） | 前端从返回的 ≤100 批次派生 | 有意改进（见下） |
| URL 编码 | 已用 `encodeURIComponent` | 强制 `encodeURIComponent` + 测试覆盖 | 1:1（明确化） |
| 多行展开 | 逐行独立 toggle | 逐行独立 toggle | 1:1 |

**员工口径决策：** 旧 `list_employees()`（`app/services/scan_history.py:122`）扫全部目录抽员工，而 `list_batches(limit=100)` 只回最近 100。旧前端用后端 `employees` 填下拉 → 选中超出 100 截断的员工会落「暂无批次」空态。本期前端改为**从返回的 ≤100 批次派生唯一员工列表**（去重 + 排序），根除「选中后无数据」的历史员工项；新 schema **不返回 `employees` 字段**，更瘦。任何零匹配仍由「暂无批次」空态兜底。

## 后端

### 端点

```
GET /api/history/scan-batches  → ScanBatchList (pydantic, extra=forbid)
```

- 路由放 `app/routes/history.py`（与 4a 同文件、同蓝图）。
- service 复用现有 `app/services/scan_history.py::list_batches(limit=100)`，路由层仅做 pydantic 投影（不重写 service）。
- `/api/*` 未登录由 `auth.py` `_require_login` 分流返回 **JSON 401**（自动继承，无需新代码）。
- service 异常不吞，向上冒泡 → 500（与 strict 端点惯例一致）。

### Schema（`app/schemas_api.py`）

```python
class ScanXlsxFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    size_bytes: int

class ScanBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: str
    employee: str
    scanned_at: str
    csv_filename: str | None      # CSV 缺失时 None
    csv_rows: int | None          # CSV 缺失或 OSError/文件 I/O 失败时 None
    csv_size_bytes: int | None    # 同上
    xlsx_files: list[ScanXlsxFile]

class ScanBatchList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    batches: list[ScanBatch]
```

> **关键修正（BLOCKER）：** `csv_filename / csv_rows / csv_size_bytes` 必须 nullable。`scan_history.py:71-83` 在 CSV 缺失或 `OSError` 时三字段均置 `None`；若 schema 设非 nullable，CSV 缺失批次会被 Pydantic 打成 500。
>
> schema **不含** `employees` 字段（见员工口径决策）。
>
> **已知潜在风险（非 4b 引入、本期不修）：** `_count_csv_rows` 用 `utf-8-sig` 打开、外层仅 `except OSError`（`scan_history.py:81,117`），非 UTF-8 的 CSV 抛 `UnicodeDecodeError` 会冒泡 → 列表端点 500。本期只做 pydantic 投影、不动 service，故仅标注；若实测命中再单开修复（service 加 GBK 回退或捕获 `UnicodeDecodeError`）。

### 生成器注册（BLOCKER）

**必须把 `ScanBatch` / `ScanXlsxFile` / `ScanBatchList` 追加进 `app/schemas_api.py` 的 `API_MODELS` 清单**（`schemas_api.py:445`）。`tools/gen_ts_types.py:63` 仅遍历 `API_MODELS` 生成 TS 类型；遗漏则 `types.gen.ts` 不产出新类型，而 `gen_ts_types.py --check` 仍可能保持绿色（无引用即无漂移）→ 类型静默缺失。

改后跑 `python tools/gen_ts_types.py` 同步 TS 类型（CI `--check` 守护漂移）。**测试断言 `types.gen.ts` 含 `ScanBatchList` / `ScanBatch` 类型**（见测试计划）。

## 前端（镜像 4a 文件结构）

| 文件 | 职责 |
|---|---|
| `frontend/src/stores/scanBatches.ts` | Pinia store；代际守卫（`batchesGen` + `initGen` + `inflight`）；lazy `ensureLoaded`；`employeeFilter`；展开集合；可重试 |
| `frontend/src/pages/history/scan-batch-types.ts` | VM 类型（camelCase） |
| `frontend/src/pages/history/scan-batch-normalize.ts` | snake_case API → camelCase VM，null 安全 |
| `frontend/src/pages/history/ScanBatchPanel.vue` | 员工下拉 + 可折叠批次行 + 下载链接 |
| `frontend/src/pages/history/HistoryPage.vue` | 批次记录 tab 内加子-tab + lazy 挂载 |

### Store 形状（`scanBatches.ts`）

比 4a `recentChanges.ts` 更简：无 detail 端点、无 mode/filter，只有列表 + 客户端员工筛选 + 展开态。

```ts
export const useScanBatchesStore = defineStore("scanBatches", () => {
  const batches = ref<ScanBatchVM[]>([]);
  const employeeFilter = ref<string | null>(null);   // null = 全部员工
  const expanded = ref<Set<string>>(new Set());       // 展开的 batchId，多行并存
  const loading = ref(false);
  const error = ref<string | null>(null);
  const loaded = ref(false);
  let inflight = false;
  let batchesGen = 0, initGen = 0;

  async function ensureLoaded() {            // 镜像 4a：lazy + initGen 守 inflight
    if (loaded.value || inflight) return;
    const my = ++initGen;
    inflight = true;
    try { await loadBatches(); }
    finally { if (my === initGen) inflight = false; }
  }

  async function loadBatches() {             // 镜像 4a：batchesGen 守过期响应
    const my = ++batchesGen;
    loading.value = true; error.value = null;
    try {
      const raw = await apiGet<ScanBatchList>("/api/history/scan-batches");
      if (my !== batchesGen) return;
      batches.value = normalizeBatches(raw);
      loaded.value = true;
    } catch (e) {
      if (my !== batchesGen) return;
      if (e instanceof UnauthenticatedError) return;   // 401 不落 error 块
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      if (my === batchesGen) loading.value = false;
    }
  }

  const employees = computed(() =>           // 口径：从返回批次派生，去重+排序
    [...new Set(batches.value.map((b) => b.employee))].sort());
  const filteredBatches = computed(() =>
    employeeFilter.value ? batches.value.filter((b) => b.employee === employeeFilter.value) : batches.value);

  function setEmployeeFilter(name: string | null) { employeeFilter.value = name; }
  function toggleExpand(batchId: string) {   // 逐行独立，多行并存
    const next = new Set(expanded.value);
    next.has(batchId) ? next.delete(batchId) : next.add(batchId);
    expanded.value = next;
  }
  function reset() {                         // 同时清 employeeFilter + 展开态
    batchesGen++; initGen++; loaded.value = false; inflight = false;
    batches.value = []; employeeFilter.value = null; expanded.value = new Set();
    loading.value = false; error.value = null;
  }

  return { batches, employeeFilter, expanded, loading, error, loaded,
           employees, filteredBatches,
           ensureLoaded, loadBatches, setEmployeeFilter, toggleExpand, reset };
});
```

### 下载链接（HIGH：强制编码）

`ScanBatchPanel.vue` 用普通同页 `<a href>`，由后端 `Content-Disposition: attachment` 触发下载，**不加 `target="_blank"`**：

```ts
const csvUrl  = (b) => `/scan_history/batches/${encodeURIComponent(b.batchId)}/download/csv`;
const zipUrl  = (b) => `/scan_history/batches/${encodeURIComponent(b.batchId)}/download/zip`;
const fileUrl = (b, name) => `/scan_history/batches/${encodeURIComponent(b.batchId)}/files/${encodeURIComponent(name)}`;
```

> **强制 `encodeURIComponent(batchId)` 和 `encodeURIComponent(fileName)`**，绝不裸字符串插值。batchId 是「员工名+价格标+时间戳」目录名、文件名可含中文/空格/`#`/`%`，未编码会被截断或解析错误 → 下载 404。旧 JS 本就这么做（`index-scan-history.js:80,86`），此处明确化并加测试。

### 子-tab 挂载（`HistoryPage.vue`）

批次记录 tab 内加子-tab 选择器；用 `scanVisited` 持久挂载：

```vue
<div v-if="batchVisited" v-show="activeTab === 'batch'">
  <div class="history__sub-tabs">
    <button :data-active="batchSubTab === 'recent'" @click="batchSubTab = 'recent'">最近改动</button>
    <button :data-active="batchSubTab === 'scan'"   @click="showScan">扫描批次</button>
  </div>
  <RecentChangesPanel v-show="batchSubTab === 'recent'" @drill="onDrill" />
  <ScanBatchPanel v-if="scanVisited" v-show="batchSubTab === 'scan'" />
</div>
```

```ts
const batchSubTab = ref<"recent" | "scan">("recent");
const scanVisited = ref(false);
function showScan() { batchSubTab.value = "scan"; scanVisited.value = true; }
// 子组件 onMounted 调 store.ensureLoaded()；scanVisited 一旦 true 不回退
```

> **首次激活挂载、切走不卸载、切回不重复请求**：`scanVisited` 置 true 后 `ScanBatchPanel` 一直挂载，子-tab 切走只 `v-show` 隐藏，store 的 `loaded` 守住不重发请求。

## 错误处理 / 边界

- 列表加载失败（非 401）→ 面板内错误条 + 「重试」按钮。重试**调 `store.ensureLoaded()`**（与 4a `RecentChangesPanel.vue:146` 一致）：错误后 `loaded` 仍为 false 故会重发，且 `inflight` 守卫防快速双击发出重复文件系统扫描。不直接调 `loadBatches`（无双击防护）。
- 401 → 早返回，不落 store error 块（交 app shell/auth 处理）。
- 空批次（`output_dir` 无目录或无匹配文件夹）→ 「暂无批次」空态。
- 员工筛选零匹配 → 「暂无批次」空态。
- 下载链接对不存在 batch/文件 → 后端旧端点已有目录穿越防护 + 404，前端不额外处理（与旧页一致）。

## 并发模型

- **两个 store（recentChanges / scanBatches）完全隔离**：独立 Pinia store、独立状态、独立加载，子-tab 切换天然不串数据。
- 代际守卫（`batchesGen` / `initGen`）保护的是 **reset 作废 pending 请求** 与 **重复请求的过期响应回填**，**不是**子-tab 切换本身。

## 测试（TDD）

### 后端 `tests/test_scan_batches_api.py`

1. 列表端点返回 strict schema，`ok=true`，`batches` 字段完整。
2. 响应顶层 + 嵌套 `ScanBatch`/`ScanXlsxFile` 的**精确 key 集合**（无多余键，extra=forbid 真实通过）。
3. **CSV 缺失批次** → `csv_filename/csv_rows/csv_size_bytes` 三字段均为 `null` 且 schema 通过（不 500）。
4. 多 XLSX 批次 → `xlsx_files` 完整且按名排序。
5. 空 `output_dir` → `batches=[]`。
6. `limit=100` 截断（造 >100 目录，断言只回 100）。
7. **未登录 → JSON 401**。
8. **service 异常冒泡 → 500**（monkeypatch `list_batches` 抛异常）。
9. **ZIP 下载端到端**（补进 `test_scan_history_routes.py`，覆盖本期新增的用户入口）：含 CSV+XLSX 的批次 `GET /scan_history/batches/{id}/download/zip` → **200 + `Content-Disposition: attachment`**，且**归档成员正确**（CSV + 各 XLSX 名齐全）；不存在批次 → **404**。
10. **TS 类型生成断言**：`ScanBatch` / `ScanXlsxFile` / `ScanBatchList` 已在 `API_MODELS` 且 `python tools/gen_ts_types.py` 后 `frontend/src/api/types.gen.ts` 含 `ScanBatchList` / `ScanBatch` 类型（防类型静默缺失）。
11. 既有 `test_scan_history_routes.py` 原有用例继续全绿（证明旧端点行为未动）。

### 前端

- `scan-batch-normalize.test.ts`：snake→camel，null 安全（三 csv_* 字段为 null 时 VM 正确）。
- `scanBatches.test.ts`：
  - lazy `ensureLoaded` 只加载一次；`initGen` 守 inflight。
  - 可重试：错误后调 `ensureLoaded()` 重发成功；`inflight` 期间重复调 `ensureLoaded()` 不发第二次请求（防双击）。
  - 401 → 不落 `error`。
  - reset 作废 pending 请求；旧请求回来不回填（`batchesGen` 守卫）。
  - reset 同时清 `employeeFilter` + `expanded`。
  - `employees` 从批次派生、去重排序；`filteredBatches` 按筛选。
  - `toggleExpand` 支持多 batchId 同时在 `expanded` 集合。
- `ScanBatchPanel` 组件测试：
  - `onMounted` → 调 `store.ensureLoaded()`（锁住 lazy 加载入口）。
  - 渲染行头摘要；CSV 缺失显示「CSV 缺失」无下载链。
  - 行头是 `<button type="button">` 且 `aria-expanded` 随展开态切换。
  - 多行可同时展开（点两行 → 两个 detail 都显示）。
  - 员工筛选无匹配 → 「暂无批次」空态。
  - **CSV/XLSX/ZIP 下载 URL 编码与链接准确**：含中文、空格、`#`、`%` 的 batchId/文件名 → 断言 href 为 `encodeURIComponent` 结果；`<a>` 无 `target="_blank"`。
- `HistoryPage` 测试：
  - 点「扫描批次」子-tab → `scanVisited` 置 true、`ScanBatchPanel` 挂载。
  - 切回「最近改动」再切回「扫描批次」→ store 不重复请求（`loaded` 守）。
- `no-analytics.test.ts`：扫描集加入 `scanBatches.ts`（新栈不得调 legacy analytics 端点）。

## 不做（YAGNI）

不删旧端点/旧页/深链（4c）；不分页/不加 RENDER_CAP；无行下钻；不重构最近改动子面板；不引表格库。
