# 前端独立化 · 阶段 0+1 设计（地基 + 简报试点页）

> **Date**: 2026-06-12（v4：三轮 review 补 Vite server.fs.allow 跨 root 读
> tokens 方案 + vitest run 非 watch + 验收 #6 三段验证；v3：401 实施点 =
> init_auth 全局闸；v2：一轮 review 4 阻断项 + 4 建议项）
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
浏览器（内网，同一域名 erp.jxwu.dev）
   │
Caddy（Coolify 管理的 proxy — 不是 Traefik）
   ├── handle /ui/*  → handle_path 剥 /ui → 前端静态容器（nginx 托管 Vite dist）
   └── 其余全部路径   → Flask（旧页 + /api/*，原样不动）
```

- 同域 ⇒ flask-login session cookie 直接复用、零 CORS。
- **/ui 前缀服务方案（2026-06-15 修订：剥前缀版，防资产 404）**：
  早期定死「Caddy 不剥 + nginx 内部按 /ui/ 提供」。实际部署发现 Coolify 用
  **Caddy**（非 Traefik），其 `/ui` Domain 默认生成 `handle_path`（**剥前缀**）。
  改为等价且更标准的机制 —— Caddy `handle_path` 剥 `/ui`，nginx 按**根**提供：
  - `vite.config.ts` 设 `base: '/ui/'`（**保持绝对**；相对 base 会把资产 404
    从「所有路由」搬到「嵌套路由」，试点单层侥幸过、嵌套时引爆）
  - `src/router.ts` history base 吃 `import.meta.env.BASE_URL`（单源=vite base）
  - Dockerfile 把 dist COPY 到 web **根** `/usr/share/nginx/html/`（非 `ui/` 子目录）
  - nginx `location / { try_files $uri $uri/ /index.html; }` —— 剥完前缀按根命中；
    资产匹配 `^/assets/...`；删旧 `return 302 /ui/`（剥前缀下自跳成死循环）；
    加 `absolute_redirect off;`（剥前缀下 nginx 绝对重定向会丢 /ui 前缀）
  - 资产 URL 是绝对 `/ui/assets/...` → 浏览器请求 `/ui/assets/x.js` → Caddy 剥
    → nginx `/assets/x.js` → 命中；任意嵌套深度都解析成 `/ui/assets/`，全深度安全。
  - 可验证：`curl /ui/assets/<hash>.js` 返回 JS（content-type 正确），
    `curl /ui/briefing` 刷新直达返回 index.html。
  - 生产验收实测（2026-06-15）：`/ui`→200、`/ui/briefing`→200、资产
    content-type=application/javascript，全过。
  - 踩坑记录：首次部署 502/重定向死循环/404 三连 = **忘点 Coolify Redeploy**，
    线上跑的还是 main 旧镜像（旧「不剥」nginx + 剥前缀 Caddy 撞出的精确指纹）；
    强制重建后症状全消。教训：改 nginx/Dockerfile 后必须确认 Coolify 真用了新镜像
    （`docker exec <c> cat /etc/nginx/conf.d/default.conf` 对比，别只看浏览器）。
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
  proxy 规则**只有 `/api` 一条**（cookie 透传到本地 Flask :5000）——
  成立前提是 §6 的 canonical 决策：新前端只消费 `/api/*`，绝不直接调
  `/briefing/data` 这类旧页端点。
- 改组件即时生效 —— 模板缓存、改 HTML 要重启、僵尸 :5000 端口三个坑
  （反例 E7 / 项目记忆）在新栈结构性消失。
- `dev.ps1` 后续加 `-Frontend` 开关一键起双进程（实施 plan 内含）。

## 5. 部署与 CI

- **Coolify**：同仓库加第二个 app，build 指向 `frontend/Dockerfile`，
  Traefik 配 PathPrefix(/ui) 规则。
- **watch paths**：若 Coolify 版本支持，前端 app 配 `frontend/**`、
  后端 app 排除 `frontend/**` —— 前端发布不再重启 Flask（不杀后台长任务，
  E10 的痛缩到只剩后端自身）；不支持则接受双触发，不劣于现状。
- **CI** 新增 frontend job，命令名定死（防 package scripts 自由发挥）：
  `npm ci` → `npm run typecheck` → `npm test`（package script 定死为
  **`vitest run` 非 watch 模式**，防 CI 挂住）→ `npm run build` →
  `npm run build-storybook`，外加 `python tools/gen_ts_types.py --check`
  与"仓库根无 package.json / package-lock.json"守护断言。
  现有 python 三腿不动。

## 6. API 与类型契约（留 Flask 的前提下拿到 FastAPI 的好处）

- **canonical 路径决策（定死）**：新前端只消费 `/api/*`。试点端点**具体
  定死为 `GET /api/briefing/data`**（与旧 `/briefing/data` 一一对照，
  响应用 pydantic schema + TS 类型；若 Task 1 核对发现需要拆分端点，
  在 plan 里列明每一条，不留通配）。现有 `/briefing/data` **只留给旧页**，
  简报迁移验收删除旧页时一并退役。Vite proxy 因此只需 `/api` 一条规则。
- 实施 plan Task 1 = 简报端点与数据形状核对，**审计范围必须包含现有
  `/briefing/data` 的消费链**（简报服务读 forecast_output.p50 ——
  红线 B1 的 computed_at 过期 + stockout_weeks_excluded 两件套要在
  新 `GET /api/briefing/data` 链路里确认处理，不只约束"新增端点"这四个字）。
- **新 API 规矩**（写进 CLAUDE.md/AGENTS.md）：请求/响应用 pydantic schema
  声明（`app/schemas.py` 先例）；`tools/gen_ts_types.py` 基于
  **pydantic `model_json_schema()`** 自写轻量转换生成
  `frontend/src/api/types.gen.ts`，**不引入重型生成器**；漂移检查命令
  定死为 `python tools/gen_ts_types.py --check`（生成物与 schema 不一致
  时退出码非 0，进 CI）。
- **401 认证契约（v3 修正实施点）**：未登录拦截发生在
  `app/auth.py::init_auth` 内的全局 `@app.before_request _require_login`
  （auth.py:101），**不是** flask-login 的 unauthorized handler——在那里
  注册 handler 永远轮不到执行（全局闸先 302）。正确改法：在
  `_require_login` 的 `not current_user.is_authenticated` 分支里，
  `request.path.startswith('/api/')` → 返回
  `401 {"error": "unauthenticated"}`（JSON），其余路径维持现有 302
  `/login`。**绝不触碰** 同函数内的 X-Upload-Token cron 分支（其
  "响亮 4xx/5xx、一律不重定向"语义是 #5 静默空转事故的修复，原样保留）。
- **认证集成测试必须用真实 app**（完整 `init_auth` 闸，不许只注册裸
  blueprint 绕过 before_request），三件套：①未登录 GET
  `/api/briefing/data` → 401 + application/json；②未登录 GET
  `/briefing` → 302 `/login`（旧页行为不回归）；③带正确
  X-Upload-Token 的 cron 路径放行不回归（错误 token 仍 401）。
- 前端 fetch 封装统一拦截 401 → `window.location = '/login?next=...'`；
  防御性兜底：`response.redirected` 或 content-type 为 text/html 时
  按未登录同样处理（防中间件行为漂移）。

## 7. Design Tokens（UI 规范化）

- **单源 = 现有 `static/css/tokens.css`，路径与格式都不动**（review 纠正：
  原稿写 `static/tokens.css` + @theme 会造成单源分裂——旧页浏览器直接
  link 的文件不能改成 Tailwind 专用格式）。该文件保持**纯 CSS 自定义
  属性**（含现有双主题变量），旧页继续直接 link。
- frontend/ 消费方式：import 同一份 `static/css/tokens.css`，然后在
  **frontend 自己的 Tailwind entry** 里做 `@theme` 映射（引用 var()），
  Tailwind 工具类由映射层生成——@theme 属于新栈私有，不污染单源文件。
- **跨 root 导入方案（v4 定死，防 Vite 白名单拒读）**：frontend 工程 root
  在 `frontend/`，import `../static/css/tokens.css` 默认会被 Vite dev
  server 的 fs 白名单拦（"outside of Vite serving allow list"）。解法：
  `vite.config.ts` 显式配 `server.fs.allow: [searchForWorkspaceRoot(...),
  '../static/css']`（或等价的仓库根白名单）；**不用复制/软链接方案**——
  那会制造第二份文件，单源名存实亡。dev 与 build 双路径都要验证该外部
  import 生效（进 §10 验收 #6）。
- 本期对 tokens.css 的改动仅限：补简报页所需但缺名的变量 + 合并明显
  重复项；全量清理散落硬编码是后续迁移的副产品，不在本期强求。
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
3. ~~仅改 `frontend/**` 的 push 不重启 Flask（watch paths）~~
   **2026-06-15 决定：watch paths 不配**（public repo 下 Coolify watch paths
   不生效 + 当前 Coolify 版本不支持/找不到该选项）。本条**永久降级为 E10 纪律**：
   后端长任务窗口（周一 14:00 scraper 那几分钟）内禁止任何 Coolify 部署。
   血的教训：2026-06-15 部署 /ui 期间 Flask 被 redeploy 打掉，撞掉 scraper 上传
   （`no available server`），靠 `scraper/reupload.ps1` 补传救回。
4. CI 前端腿（type-check + vitest + build + storybook build）绿，
   python 三腿不受影响
5. 新旧简报页并存可访问，行为一致
6. tokens 单源生效（三段验证）：`npm run dev` 能加载跨 root 的
   token CSS；`npm run build` 产物包含 token 变量；改
   `static/css/tokens.css` 一个色值后旧页与 `/ui/briefing` 同步变化
7. Storybook 本地可跑，基础组件 + tokens 页齐全
8. 新 API 端点有 pydantic schema，`types.gen.ts` 与 schema 一致
   （`gen_ts_types.py --check` 进 CI）
9. `/ui/briefing` 浏览器刷新直达 200（SPA fallback 生效，非 404）
10. `/ui/assets/*` 实际返回 JS/CSS（content-type 正确），不是 index.html
11. 未登录 fetch `/api/*` 返回 JSON 401（不是登录页 HTML / 302）
12. 仓库根无 package.json / package-lock.json（CI 守护断言）

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
| 简报页 API 现状不明 | 实施 plan Task 1 = 端点核对（含现有 /briefing/data 消费链审计），spec 不预设 |
| Node 供应链引入 | 锁 package-lock + frontend 圈定 + CI npm ci 固定解析 + 根目录无 Node 守护断言 |
| 401 契约改动影响旧页/cron | `_require_login` 内仅对 /api/* 分流，其余路径 302 与 X-Upload-Token 分支原样；§6 集成测试三件套守护 |

**实施前置**：仓库根当前有一个 untracked `package-lock.json`，与"根目录
无 Node 痕迹"冲突——实施 plan 第一步**先确认来源**（对照内容判断是否
npx/codegraph 残留、是否用户有意保留），确认后删除或迁移，不默认删
未知的用户产物。
