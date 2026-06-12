# 前端独立化 · 阶段 0+1 设计（地基 + 简报试点页）

> **Date**: 2026-06-12
> **状态**: 设计稿待用户审阅（审阅通过后出实施 plan）
> **作者**: Fable 5（brainstorming 产出）
> **决策记录**: 用户痛点全选（开发体验/现代框架/代码组织/部署分离）；
> 策略=地基+试点页；框架=Vue 3 + Vite + TS；形态=同仓 frontend/ + 独立静态服务；
> 后端=**留 Flask 不迁**（见 §9）；增补 design tokens（§7）与 Storybook（§8）。

## 1. 目标与非目标

**目标**（阶段 0+1，全部验收标准见 §10）：
- 建立独立前端工程的完整地基：开发（热重载）→ 构建 → 部署（独立发布）→ 认证 → API 契约 → 组件规范（tokens + Storybook）
- 迁移 1 个试点页（简报页）验证全链路，新旧并存
- 固化 design tokens 单源，新旧两栈同时消费

**非目标**（明确不做，防 scope 蔓延）：
- 不迁移除简报外的任何页面（验收后另行排期，随停随走）
- 不迁登录页（SPA 401 → 跳转 Flask 登录页）
- 不迁 PDA 扫描页（真机坑 E7，永远排在迁移序列最后）
- 不引入 SSR / 不换后端框架 / 不做组件库对外发布
- Storybook 不部署（本地 + CI build 产物）

## 2. 架构与路由拓扑

```
浏览器（内网，同一域名）
   │
Traefik（Coolify 管理）
   ├── PathPrefix(/ui)  → 前端静态服务容器（nginx/caddy，托管 Vite dist）
   └── 其余全部路径      → Flask（旧页 + /api/*，原样不动）
```

- 同域 ⇒ flask-login session cookie 直接复用、零 CORS。
- Vue Router `base: '/ui/'`，history 模式；静态服务配 SPA fallback
  （未命中文件 → index.html）。
- 双栈并存：旧简报页保留原路径；新版 `/ui/briefing`。验收通过后旧页删除，
  原路径 302 → `/ui/briefing`。

## 3. frontend/ 工程

```
frontend/
├── package.json            # Node 工具链严格圈在本目录，仓库根保持无 Node
├── vite.config.ts          # @tailwindcss/vite + dev proxy → :5000
├── tsconfig.json
├── index.html
├── src/
│   ├── main.ts / App.vue / router.ts
│   ├── stores/             # Pinia
│   ├── api/                # typed fetch 封装 + 生成的 TS 类型（见 §6）
│   ├── components/         # 基础组件（每个配 story）
│   └── pages/briefing/     # 试点页
├── .storybook/             # §8
└── Dockerfile              # 多阶段：node build → 静态服务
```

技术选型：Vue 3（Composition API + `<script setup>`）+ TypeScript + Pinia +
Vue Router + Tailwind v4（`@tailwindcss/vite`）。

**Node 回归声明**：Phase 4（重构 plan）曾把 Node 配置清出仓库；本设计**有意识
地重新引入**，约束 = package.json/node_modules 只存在于 `frontend/`，根目录
不出现任何 Node 痕迹。CI 前端腿独立 setup-node。

## 4. 开发体验

- `cd frontend && npm run dev` → Vite :5173，HMR 热重载；
  `/api` 与会话路径 proxy 到本地 Flask :5000（cookie 透传）。
- 改组件即时生效 —— 模板缓存、改 HTML 要重启、僵尸 :5000 端口三个坑
  （反例 E7 / 项目记忆）在新栈结构性消失。
- `dev.ps1` 后续加 `-Frontend` 开关一键起双进程（实施 plan 内含）。

## 5. 部署与 CI

- **Coolify**：同仓库加第二个 app，build 指向 `frontend/Dockerfile`，
  Traefik 配 PathPrefix(/ui) 规则。
- **watch paths**：若 Coolify 版本支持，前端 app 配 `frontend/**`、
  后端 app 排除 `frontend/**` —— 前端发布不再重启 Flask（不杀后台长任务，
  E10 的痛缩到只剩后端自身）；不支持则接受双触发，不劣于现状。
- **CI** 新增 frontend job：`npm ci` → type-check → vitest → build →
  Storybook build（防 story 腐烂）。现有 python 三腿不动。

## 6. API 与类型契约（留 Flask 的前提下拿到 FastAPI 的好处）

- 试点所需端点：核对简报页现有 routes，缺 JSON 端点则在
  `app/routes/analytics.py`（或对应蓝图）补 `/api/briefing/*`。
  实施 plan 第一个 Task 就是这次核对（端点清单进 plan，不在 spec 拍脑袋）。
- **新 API 规矩**（写进 CLAUDE.md/AGENTS.md）：请求/响应用 pydantic schema
  声明（`app/schemas.py` 先例）；新增 `tools/gen_ts_types.py` 从 pydantic
  模型生成 `frontend/src/api/types.gen.ts`（CI 校验生成物与 schema 同步，
  漂移即红）。
- 消费 forecast_output 类数据的端点遵守红线 B1（computed_at 过期 +
  stockout_weeks_excluded 两件套）。
- 认证：same-origin fetch 自带 session cookie；401 统一拦截 →
  `window.location = '/login?next=...'`。

## 7. Design Tokens（UI 规范化）

- 单源文件 `static/tokens.css`（位置让新旧两栈都能引）：Tailwind v4
  `@theme` 声明色板/间距/字号/圆角/阴影 + 现有**双主题**变量。
- 消费：旧页 standalone CLI 构建引入（替换散落的硬编码值**仅限简报页
  相关与明显重复项**，全量清理是后续迁移的副产品，不在本期强求）；
  frontend/ 经 `@tailwindcss/vite` 引入同一文件。
- 验收：改一个 token 色值，旧页与 /ui 新页同时变。
- 来源：前端重排第二轮（docs/design 红稿）已沉淀的视觉决策——本节是把
  它们从"散在 CSS 里"升格为"有名字的规范"。

## 8. Storybook

- Storybook 8 + vue3-vite 框架，放 `frontend/.storybook/`。
- 范围：试点页拆出的基础组件（预计 Table / Card / Badge / StatusBar /
  PageHeader 一类）每个一个 story + 一页 tokens 可视化（色板/间距/字号表）。
- 只本地运行 + CI build；不部署（要看再说，YAGNI）。
- 选型说明：Histoire 更轻，但 Storybook 生态/插件/AI 语料强一档，
  组件库会随迁移长大，选 Storybook。

## 9. 后端决策：留 Flask（已与用户确认）

- **Go/Rust 重写：否决**。后端核心资产 = pandas/numpy 预测/回测/ETL 数值层
  （刚完成审计 + golden 守护的部分），换语言 = 推倒全系统验证最充分的资产，
  内网单操作员场景无性能消费者，论文依赖本代码库。
- **FastAPI 迁移：否决**。async 无用武之地（pandas/DB 密集非高并发）；
  pydantic 已在用；唯一真价值（OpenAPI/类型契约）由 §6 增量获得，零迁移成本。
- **保留升级路径**：§6 的 pydantic schema 约定与未来任何框架兼容；
  若有朝一日真换，schema 直接复用。

## 10. 试点验收标准（全过才排后续页面迁移）

1. 本地 `npm run dev` 热重载：改简报组件免重启即生效
2. 生产 `/ui/briefing` 登录态下数据与旧简报页一致
3. 仅改 `frontend/**` 的 push 不重启 Flask（验证后台长任务存活；
   若 Coolify 不支持 watch paths，本条降级为"前端容器独立重建成功"）
4. CI 前端腿（type-check + vitest + build + storybook build）绿，
   python 三腿不受影响
5. 新旧简报页并存可访问，行为一致
6. tokens 单源生效：改一个色值，新旧两页同步变化
7. Storybook 本地可跑，基础组件 + tokens 页齐全
8. 新 API 端点有 pydantic schema，`types.gen.ts` 与 schema 一致（CI 校验）

## 11. 双栈期规范（验收后写进 CLAUDE.md / AGENTS.md）

- 新功能页一律 `frontend/`；旧页只修 bug 不加功能（防双栈漂移）
- 迁移排期原则：高频决策页（补货/货号历史）优先，PDA 最后
- 每迁一页：旧页删除 + 原路径 302 + e2e 烟雾更新，不留死链

## 12. 风险与对策

| 风险 | 对策 |
|---|---|
| 双栈并存期长，视觉/行为漂移 | tokens 单源（§7）+ 双栈期规范（§11） |
| Coolify watch paths 不可用 → 前端 push 仍杀后端任务 | 验收标准 3 降级条款；长任务窗口照旧走 E10 纪律 |
| Storybook/类型生成变成没人维护的摆设 | 全部进 CI（story build 红 = 立刻发现；types.gen 漂移 = 红） |
| 简报页 API 现状不明 | 实施 plan Task 1 = 端点核对，spec 不预设 |
| Node 供应链引入 | 锁 package-lock + frontend 圈定 + CI npm ci 固定解析 |
