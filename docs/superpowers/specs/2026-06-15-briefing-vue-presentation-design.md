# 晨间简报 Vue 呈现层迁移 — 设计

**Date:** 2026-06-15
**Status:** 待审批
**Owner:** jxwu1
**前置:** [[project_frontend_decoupling]] 前端独立化 §11；数据口径源 = `docs/superpowers/specs/2026-06-09-morning-briefing-design.md`

---

## 1. 背景与范围

晨间简报数据后端（`app/services/briefing.py` + `/api/briefing/data`）与口径已按 2026-06-09 spec 实现并上线。前端独立化时简报页迁到新 Vue 栈 `/ui/briefing`，但只搭了**骨架**：`BriefingPage.vue` 把每张 card 直接 `<pre>{{ card }}</pre>` 倒原始 JSON，且 `actions`（3 个行动清单）**完全没渲染**。

本设计只定 **Vue 呈现层**，把已批准的 5 卡片 + 3 行动清单正确落到新栈。

### 范围内
- 重写 `frontend/src/pages/briefing/` 下的页面与组件、`stores/briefing.ts` 的数据收窄。
- 新增 legacy `static/js/store.js` 的 tab 深链兼容（前端，纯兼容改动）。

### 非范围（明确不做）
- **不改后端**：`app/services/briefing.py`、`app/schemas_api.py`、`/api/briefing/data` 不动。
- 不改数据口径（沿用 2026-06-09 spec §4/§5/§6）。
- 不改默认登录落页（2026-06-09 spec §10 待议）。
- 不建表 / 不加 cron / 不做图表。

---

## 2. 数据来源（只读）

- 端点：`GET /api/briefing/data`（canonical），未登录由 `apiGet` 跳转接管。
- 顶层 payload（既有，见 2026-06-09 spec §6）：
  `{ ok, generated_at, data_week, data_week_complete, cards{...×5}, actions{...×3} }`
- TS 生成类型 `BriefingData`（`api/types.gen.ts`）中 cards/actions 内层是 `Record<string, unknown>`（后端 schema 为 `dict[str, Any]`，本次不收紧后端）。内层精确字段见 `app/services/briefing.py` 各 `compute_*` / `build_*` 返回。

---

## 3. 布局（方案 C — 按阅读优先级单列流）

桌面全宽（侧栏 200px 外的主内容区，不做移动端适配）。自上而下：

```
PageHeader: 晨间简报 / 数据周 <data_week> · 数据刷新于 <last_import_date>
[stale 红条]（条件渲染）
── 销售健康 Hero（大卡，绿/红左边条 + 大号 delta% + 一句话副信息）
── 分组标题「今天要动手的」
   3 栏 grid：建议补货 | 建议催·确认 | 建议复查异常（各 ActionList 表格 + 查看全部→）
── 分组标题「状态」
   4 栏 grid：补货风险 | 缺货影响 | 压货风险 | 数据健康（StatCard）
```

视觉沿用 `static/css/tokens.css` token + 现有设计系统（Linear 风格，见 `docs/design/design-context.md`）。

---

## 4. 组件拆分（`frontend/src/pages/briefing/`）

| 组件 | 职责 | 依赖 |
|---|---|---|
| `BriefingPage.vue` | 编排：PageHeader + stale 红条 + 三段；loading/error/空库分支 | store, 下列组件 |
| `SalesHealthHero.vue` | 销售健康 hero；按 status 分支渲染（见 §6） | Badge |
| `ActionList.vue` | 通用行动清单表格（props: `title`、列定义、`rows`、`total`、`href`）；复用 3 次 | — |
| `StatCard.vue` | 状态小卡（label + 大数字 + 一句话） | Badge |

- 复用现有 `PageHeader`（title+subtitle）、`Badge`（tone: ok/warn/danger/muted）。
- `Card.vue` 仅 title slot，不满足 Hero/StatCard 需求 → 自建，合理。

---

## 5. 类型收窄（normalize 是唯一边界）

**硬验收 #1：`normalizeBriefing(raw)` 是 API 边界的唯一收窄点；组件只吃 `BriefingViewModel`，不接触 raw payload。禁止用裸 `as` 断言穿透 `Record<string, unknown>`。**

- `frontend/src/pages/briefing/types.ts`：
  - view-model 接口：`SalesHealthVM`、`RestockRiskVM`、`StockoutImpactVM`、`OverstockVM`、`DataHealthVM`、`RestockActionVM`/`FollowUpActionVM`/`ReviewActionVM`，以及包裹型 `Unavailable = { available: false }`。
  - `BriefingViewModel`：各 card/action 为 `<具体VM> | Unavailable`。
- `frontend/src/pages/briefing/normalize.ts`：`normalizeBriefing(raw: BriefingData): BriefingViewModel`
  - 逐 block 读字段、做类型/存在性校验，构造对应 VM。
  - **硬验收 #2：某 block `ok===false`、缺字段或字段类型不符 → 该 block 收窄成 `Unavailable`（局部「暂不可用」），绝不 throw 到整页 error。** 整页 error 仅留给 `apiGet` 的系统级失败（5xx）。
- `stores/briefing.ts`：`load()` 取 raw 后存 `normalizeBriefing(raw)`；store 暴露的是 `BriefingViewModel | null`。系统级失败（非 `UnauthenticatedError`）仍走 `error`。

---

## 6. 状态分支（按 2026-06-09 spec §6）

- **loading**：占位。
- **系统级 error**（apiGet 抛非 401）：整页错误态。
- **空库**：`data_week === null` → 友好空态（「本批次暂无完整数据周」），不报红。
- **per-block unavailable**：对应卡/清单显「暂不可用」，其余正常。
- **销售健康 Hero 按 `status` 分支**：
  - `ok` → delta% + 涨跌量 + 副信息（下期预期 `forecast_next_p50`、模型校准 `model_bias_units`）。
  - `week_incomplete` / `coverage_insufficient` / `no_previous_week` → **不显 delta%**，显对应文案（口径见 2026-06-09 spec §4）。
- **压货 `cost_available===false`** → 只显件数 + 库存量（`stock_qty`）+「无成本数据」，不显金额。
- **数据健康红条**：`data_health.stale === true` 或 `scrape_stale === true` → 顶部红条。
  - **硬验收 #5：`days_since == null` 时文案固定为「刷新时间未知」，不拼「N 天」。** 有值时「数据已超过 N 天未刷新」。

---

## 7. 深链（统一 /?page=，并改 legacy store）

目标页（补货/采购/数据质量）仍在旧 Alpine 站，与 `/ui` 是两个独立 SPA。已核实：
- `/restock`、`/purchase` **无 GET 页面路由**（仅 `/restock/decisions...`、`/purchase/orders` 等 API），直达会 404。
- `/` 经 `app/routes/pages_tasks.py::index()` 渲染 `index.html`（旧 SPA）。
- `restock`/`purchase`/`data_quality` 均为合法 `pages[].id`（`static/js/store.js:162/165/174`）。

### 方案
3 个「查看全部 →」统一指向旧 SPA 根 + 显式 tab 参数，同标签跳转（离开 `/ui`）：

**硬验收 #3：实际链接为 `/?page=restock`、`/?page=purchase`、`/?page=data_quality`，参数不带空格。**

### legacy 兼容（classic script，禁 ESM）
**约束（阻断级）**：`static/js/store.js` 在 `templates/index.html:13` 以 classic `<script defer>` 加载（**非** `type="module"`）。**绝不给 store.js 或新文件加 `export`/`import`** —— 旧 SPA 首页会直接语法错打挂。

- 纯函数 `resolveInitialPage(pathname, search, pageIds)` 放**新文件 `static/js/nav-resolve.js`**（classic，顶层函数声明，无 export），返回应激活的 page id 或 `null`。
- `templates/index.html` 在 store.js 之前加 `<script defer src=".../nav-resolve.js">`（defer 按序执行，store.js 运行时该全局函数已就绪）。
- **硬验收 #4：优先级 = query `page` 命中 `pageIds` > pathname 首段命中 `pageIds` > 返回 null（保留默认 `current`）。**
- `initFromStorage()` 改为调用该全局函数：`const seg = resolveInitialPage(location.pathname, location.search, this.pages.map(p=>p.id)); if (seg) this.current = seg;`
- legacy 改动仅限：新增 `nav-resolve.js`、`index.html` 加一行 script、`store.js` 改 `initFromStorage` 一处；后端不动。

---

## 8. 测试

### 前端（vitest）
- `normalize.test.ts`：
  - 各 card/action 正常 payload → 正确 VM。
  - **malformed / 缺字段 / `ok:false` block → 被收窄成 `Unavailable`（不 throw）。**
  - 销售健康各 status 分支 → 正确 VM 形态。
  - 压货 `cost_available:false` → 金额字段缺省。
- 组件渲染测（沿用 `briefing.test.ts` 风格）：Hero 各 status、ActionList 空/有数据、StatCard、stale 红条（含 `days_since==null` → 「刷新时间未知」）、空库空态。
- store：系统级失败走 error；401 不渲染误导文案。

### legacy（nav-resolve.js）
- `resolveInitialPage` 单测：
  - `?page=restock|purchase|data_quality` → 对应 id。
  - query 命中优先于 pathname；query 未命中回退 pathname；都不命中 → null。
  - 非法 page 值 → null。
- **测试落点（不靠 ESM import）**：vitest 用 `fs.readFileSync` 读 `static/js/nav-resolve.js`，经 `new Function(code + "; return resolveInitialPage;")()` 取出函数再断言。`nav-resolve.js` 保持 classic（无 export），所以**不能** `import` 它——只能这样 eval 验证。

---

## 9. 验收标准

1. `/ui/briefing` 渲染 5 卡片 + 3 行动清单（不再有裸 JSON `<pre>`），布局符合 §3 方案 C。
2. 硬验收 #1–#5 全部成立（见 §5/§6/§7）。
3. 销售健康 Hero 各降级 status 正确不显 delta%；压货成本缺失降级；stale 红条（含未知文案）。
4. 3 个「查看全部」点击跳到 `/?page=...` 并激活旧 SPA 对应 tab。
5. per-block 失败显「暂不可用」不白屏；系统级 5xx 整页 error；空库友好空态。
6. `cd frontend && npm run test` 全绿（含 normalize + resolveInitialPage）；`npm run build` 通过。
7. `python tools/gen_ts_types.py --check` 不漂移（后端 schema 未改，预期无变化）。
8. 后端无改动（`git diff` 不含 `app/` Python 文件）。

---

## 10. 风险与待确认

- 旧 SPA 在 `/?page=restock` 加载后能否稳定停在目标 tab，取决于 `initFromStorage` 在 Alpine 初始化时序里先于其它 current 写入；实施时本地实测三页跳转。
- 线上成本列覆盖率（[[project_local_pg_derived_cols_empty]]）影响压货卡展示分支，本地走降级路径开发，线上由数据健康卡实时暴露。
