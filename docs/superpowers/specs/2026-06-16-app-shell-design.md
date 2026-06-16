# App Shell（新 Vite 栈导航壳）设计 spec

**Status:** 设计待批准
**Date:** 2026-06-16
**关联:** 前端独立化 spec `2026-06-12-frontend-decoupling-design.md` §11；简报迁移 `2026-06-15-briefing-vue-presentation-design.md`

## 1. 背景与目标

新 Vite 栈目前只有简报一个**裸路由**（`/ui/briefing`），无侧栏、无导航。迁移下一个页面（货号历史）前，需先给新栈搭**导航壳**：复刻旧 SPA 侧栏，让已迁页走 Vue 路由、未迁页跳回旧 SPA。本 spec 只覆盖 **App Shell**（地基），货号历史页是**独立后续 spec**。

**目标**：新栈从"只有简报一个裸路由"→"带完整侧栏的壳，简报在壳里，其余项跳旧 SPA"。可独立上线验收，后续每迁一页只是把侧栏某项从"跳旧栈"改成"Vue 路由"。

## 2. 范围

**In**
- 后端：新增 `GET /api/me`（pydantic）→ `{display_name, is_admin}`。
- 前端：`AppShell.vue`（侧栏 + header + `<RouterView>`）、`SidebarNav.vue`、`AppHeader.vue`、`IconSprite.vue`、`nav-items.ts`（导航单一真源）、`useCurrentUser`（pinia）、主题切换。
- 简报并入壳：`/briefing` 从裸路由变成壳的子路由。

**Out（明确不做）**
- 货号历史及其它页迁移（各自后续 spec）。
- substrip（SESSION/OPERATOR/WAREHOUSE/STOCKPILE 那条扫描工作流横条）—— **砍掉，不复刻**。
- 主题持久化到服务端（见 §8.3，改为浏览器本地）。

## 3. 架构

```
frontend/src/
├── App.vue                      # 改：渲染 <RouterView/>（壳由 layout 路由提供）
├── router.ts                    # 改：layout 路由(AppShell) 包 children
├── shell/
│   ├── AppShell.vue             # 侧栏 + header + <RouterView/> + <IconSprite/>
│   ├── SidebarNav.vue           # 导航列表（active/admin门控/collapse/迁移分流）
│   ├── AppHeader.vue            # 实时时钟（无 substrip）
│   ├── IconSprite.vue           # SVG sprite，AppShell 根部挂载一次
│   ├── nav-items.ts             # 13 项导航单一真源
│   └── ThemeToggle.vue          # DARK/LIGHT，写 localStorage
└── stores/
    └── currentUser.ts           # useCurrentUser：fetch /api/me
```

后端零新表；仅加一个只读端点 + 一处 auth 例外。

## 4. 后端 `/api/me`

**端点**：`GET /api/me`，session auth，只读。新建 `app/routes/me.py`，blueprint `api_me`（`url_prefix="/api"`，注册到 app）。放新文件而非塞进 `/api/briefing`（语义独立）。

**Schema**（加入 `app/schemas_api.py` 的 `API_MODELS`，约 :47）：
```python
class MeData(BaseModel):
    display_name: str   # = current_user.display_name or current_user.username（后端兜底，前端不处理 nullable）
    is_admin: bool
```

**实现**：
```python
@api_bp.get("/me")
def me():
    return jsonify(MeData(
        display_name=current_user.display_name or current_user.username,
        is_admin=getattr(current_user, "role", "admin") == "admin",
    ).model_dump())
```

**关键 auth 修正（review 必调项）**：`app/auth.py` `_require_login` 第 119-122 行——已登录 `role=="scanner"` 的非 `pda./auth./static` 请求会 302 跳 PDA，**不豁免 `/api/*`**。`/api/me` 的端点（`api_*.me`）必须加进该例外，否则 scanner 调 `/api/me` 被跳 PDA 而非拿 JSON（也无法测 `is_admin=false`）。

修正：第 121 行 scanner 例外用 **path 判断**（不靠端点名拼接）——放行 `request.path == "/api/me"`，让任何已登录用户都能拿到 JSON。未登录仍走第 125 行 `/api/*` → JSON 401（不变）。

**TS 类型**：`MeData` 入 `API_MODELS` 后，验收必须跑 `python tools/gen_ts_types.py`（生成）+ `--check`（CI 守护漂移）。

## 5. 前端组件

- **`AppShell.vue`**：根布局。结构 = `<IconSprite/>` + `<aside>`(SidebarNav + 底部用户/登出 + ThemeToggle) + `<div>`(AppHeader + `<RouterView/>`)。挂载时触发 `useCurrentUser().load()`。
- **`SidebarNav.vue`**：消费 `nav-items.ts` + 当前路由 + `useCurrentUser`。渲染 "MODULES · N" + 列表。每项：
  - 图标 `<svg><use :href="'#icon-' + item.icon"/></svg>`（指向 sprite symbol）。
  - active：migrated 项按当前 route 高亮；未迁项不高亮（用户在旧栈时本组件不渲染）。
  - **迁移分流**：`item.routeName` 存在 → `<RouterLink :to>`；否则 → `<a :href="'/?page=' + item.legacyPageId">`（整页跳旧 SPA）。
  - admin 门控：`!isAdmin` 时隐藏 `requiresAdmin` 项（pda_pending / admin）。
- **`AppHeader.vue`**：实时时钟，`onMounted` 起 `setInterval`，**`onUnmounted` 清 interval**。无 substrip。
- **`IconSprite.vue`**：内联 SVG sprite（从旧栈 `index.html` 的 9 模块 sprite 移植），`width=0 height=0 position:absolute`。AppShell 根部挂载**一次**。
- **`ThemeToggle.vue`**：DARK/LIGHT 两按钮，写 `localStorage['theme']` + `document.documentElement.dataset.theme`（复用旧栈 bootstrap 同 key）。**不 PUT 服务端**（见 §8.3）。

## 6. 导航数据模型 `nav-items.ts`

单一真源，避免字符串拼接猜测（review 小修）：
```ts
export interface NavItem {
  id: string;              // 'briefing' / 'dashboard' / ...
  label: string;           // '晨间简报' / '总览'
  icon: string;            // sprite symbol 名（'briefing' → #icon-briefing）
  code: string;            // '00' 等角标
  routeName?: string;      // 已迁 → vue-router route name（如 'briefing'）
  legacyPageId?: string;   // 未迁 → 旧 SPA /?page=<id>
  requiresAdmin?: boolean; // pda_pending / admin = true
}
```
约束：每项 **`routeName` 与 `legacyPageId` 二选一必有其一**。当前仅 `briefing` 有 `routeName`，其余有 `legacyPageId`。13 项 + 顺序/分组对齐旧 `store.js` nav.pages。

## 7. 路由

```ts
{
  path: "/",
  component: AppShell,
  children: [
    { path: "", redirect: { name: "briefing" } },
    { path: "briefing", name: "briefing", component: () => import("./pages/briefing/BriefingPage.vue") },
    // 后续：{ path: "history", name: "history", ... }
  ],
}
```
子路由用**相对 path**（`briefing` 不带前导 `/`，review 小修）。`history: createWebHistory(import.meta.env.BASE_URL)` 不变（base `/ui/`）。

## 8. 状态与行为

### 8.1 useCurrentUser（pinia）
```ts
state: { displayName: string | null, isAdmin: boolean }  // 初始 isAdmin=false（安全默认）
load(): 调 apiGet<MeData>("/api/me")
```
- **401 处理（review 必调）**：`apiGet` 抛 `UnauthenticatedError` → **不吞**，让 `client.ts` 的登录跳转接管（同简报 store）。
- **仅 500/网络失败** → 降级 `isAdmin=false`、`displayName` 留兜底（如空或 "—"）。
- **不缓存 isAdmin 到 localStorage**（review：避免角色变化后 stale privilege）。

### 8.2 collapse
复用旧 key `localStorage['nav.collapsed']`（与旧栈同步）。

### 8.3 主题（决策 B：浏览器本地）
新栈主题切换**只写 `localStorage['theme']` + data-theme**，**不 PUT `/admin/api/theme`**。
**语义变化（明确记录）**：主题从"账号偏好"（旧栈 PUT 写库 + 登录把库值写回 localStorage）变为"**当前浏览器偏好**"。后果：重新登录时旧 SPA 登录流可能用库里旧 theme 覆盖 localStorage；跨设备不一致。**已接受此产品语义**。

### 8.4 admin 门控
**仅显示层门控**——隐藏 admin-only 导航项。**不是权限控制**：真实权限仍由后端 `require_role("admin")` 与旧路由把守。失败默认隐藏（安全默认）。

## 9. 图标
sprite 由 `IconSprite.vue` 在 AppShell 根部挂载**一次**；`SidebarNav` 只 `<use href="#icon-x">`。
旧栈 sprite 是「9 模块」，但 `nav-items.ts` 13 项去重后约 10 个 distinct icon —— **移植时须确保 sprite 含 nav-items 引用的全部 icon**（缺的补 symbol）。**单测**：`nav-items.ts` 每个 `icon` 都能在 sprite 里找到对应 `<symbol id="icon-...">`（防空图标）；这条测试即上面"补全"的守护。

## 10. 错误处理
- `/api/me` 401 → 登录跳转（apiGet 接管）。
- `/api/me` 500/网络 → `isAdmin=false`、显示降级名，壳照常渲染（导航可用，admin 项隐藏）。
- 未迁项跳 `/?page=id` 是整页导航，离开 Vue 栈，无需 Vue 错误处理。

## 11. 测试

**前端 unit（vitest）**
- `SidebarNav`：渲染 N 项 + "MODULES · N"；active 高亮当前 route；`!isAdmin` 隐藏 requiresAdmin 项，`isAdmin` 显示；migrated 项渲染 `RouterLink`、未迁项渲染 `<a href="/?page=id">`（href 无空格）。
- `nav-items.ts` × sprite：每个 icon 有对应 symbol。
- `useCurrentUser`：load 填充 displayName/isAdmin；401 透传（不吞）；500 → isAdmin=false。
- `AppHeader`：渲染时钟；unmount 清 interval（断言不再 tick）。
- `AppShell`：渲染侧栏 + `<RouterView/>`；挂载触发 load。

**后端**
- `/api/me`：admin → `{is_admin:true, display_name}`；scanner → `{is_admin:false}`（**且不被 302 到 PDA**，验证 auth 例外）；未登录 → JSON 401。

## 12. 验收标准
1. 前端 `npm run test` 全绿（新组件 + 既有简报/components）。
2. `npm run build`（vue-tsc + vite）绿。
3. `python tools/gen_ts_types.py --check` exit 0（`MeData` 已生成、无漂移）。
4. `git diff --stat main...HEAD -- app/` 仅 `auth.py`（加例外）+ `schemas_api.py`（加 MeData）+ 新 `/api/me` 路由文件；无其它后端改动。
5. 本地端到端：`/ui/briefing` 在壳里渲染（侧栏 + header + 简报内容）；侧栏点已迁项（简报）走 Vue 路由不刷整页；点未迁项跳 `/?page=id` 落旧 SPA 对应 tab；admin 门控按 `/api/me` 生效；DARK/LIGHT 切换即时生效且刷新保持；无 substrip。

## 13. 双栈期注记（§11）
- 简报并入壳（子路由），无旧页可删（简报旧页早已 302）。
- 后续迁页：新增 `/api/<域>/*`（pydantic）+ Vue 页 + 把 `nav-items.ts` 对应项从 `legacyPageId` 换成 `routeName` + 旧页删除 + 原路径 302 + e2e 烟雾。
