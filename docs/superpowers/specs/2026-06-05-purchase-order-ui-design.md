# 采购订单跟踪 UI — 设计

**日期：** 2026-06-05
**分支：** feat/purchase-order-ui
**状态：** 待实现

## 背景与目标

采购单（`purchase_orders` 表）在 `/purchase/export` 时作为副作用创建（status=placed）。后端已有完整跟踪能力：

- `GET /purchase/orders` — 列最近 50 单（含 supplier_name / 日期 / 状态 / 金额）
- `POST /purchase/orders/<id>/arrival` — 标到货（设 arrived + 同步明细 qty_arrived = qty_ordered，整单全到）
- `POST /purchase/orders/<id>/update` — 只改 order_date（误带 arrival_date → 400）
- `POST /purchase/orders/<id>/void` — 软删 status='void'，并排除出供应商前置期统计

**问题：** 这些路由没有任何前端在调用，订单创建后无法标到货 / 改期 / 作废。

**目标：** 在采购页内新增「订单跟踪」面板，让单操作员能看到已下采购单并执行上述三种操作。

## 范围

**做：** 订单列表 + 行内标到货 / 改期 / 作废 + 错误展示 + 刷新。

**不做（YAGNI，单操作员 50 单够用）：** 分页、搜索、部分到货拆行、批量操作、独立导航页。

## 架构

### 后端
无改动。复用现有 4 个路由。

### 前端：新模块 `static/js/purchase_orders.js`
- 独立小文件，不肿大 1046 行的 `purchase.js`。
- 导出 `initPurchaseOrders(container)`：拉取 `GET /purchase/orders` → 渲染表格 → 用**事件委托**绑定行内操作。
- `purchase.js` 改动（最小）：
  1. 顶部 `import { initPurchaseOrders } from "./purchase_orders.js";`
  2. `pagePurchase` 模板最底部加 `<section class="pnl" id="purOrders"></section>`
  3. `init()` 末尾调 `initPurchaseOrders(document.getElementById("purOrders"))`

### 幂等性
`purchase.js` 的 `init()` 只跑一次，容器持久存在。模块仍要保证幂等：
- 重复 `init` 时先清空 container（`container.innerHTML = ''`）再渲染。
- 行内操作用**单个事件委托**监听器绑在 container 上，不给每行单独绑定 → 重渲染不累积监听器。

## 布局（必须项）

采购页是固定视口布局（`components.css:674` `#pagePurchase.active { overflow: hidden }`，`:654` `height: calc(100vh - 76px)` flex 列）。面板 01 `flex-shrink:0`，02 解析区靠 flex 吃剩余空间。新面板若默认 flex 会压缩 02/03 或被 overflow:hidden 裁掉。

**约束：**
- `#purOrders.pnl { flex-shrink: 0 }` — 不抢 02 的弹性空间。
- 内部表格容器 `max-height: 260px; overflow-y: auto` — 50 单也只占固定高度，内部滚动。
- **可折叠，默认展开** — 订单多时操作员可收起，让回空间给 02 解析区。收起后仅剩标题栏。
- 放在面板最底部（01 → 02 → 03 → 04 purOrders）。
- CSS 加在 `static/css/components.css`，复用现有 `.pnl` / `.pnl-hd` / `.pnl-bd` token。

## 列表与交互

| status | 中文 | 列显示 | 操作 |
|---|---|---|---|
| placed | 已下单 | 供应商 / 下单日 / — / 金额€ | `[标到货] [改期] [作废]` |
| arrived | 已到货 | …含到货日 | `[改期]` |
| void | 已作废 | 灰显 | 无 |

**status 白名单映射（必须项）：** 中文标签与操作集都由前端**白名单**驱动（仅 placed / arrived / void 三键）。命中白名单 → 显示对应中文 + 操作；**未命中**（后端将来新增状态）→ 状态列显示 `esc(原始 status 值)`，**不给任何操作按钮**，避免前端把未知态误判成 placed 而错配作废/到货按钮。

- **标到货**：点击 → 行内展开 `<input type="date">`（默认今天，可改）+ 确认/取消 → `POST /arrival {arrival_date}`。整单全到，不拆行。
- **改期**：同款行内 date 编辑器，预填当前 order_date → `POST /update {order_date}`。
- **作废**：`confirm("确认作废该采购单？作废后不计入前置期统计")` → `POST /void`。
- 任一操作成功 → 重新拉 `GET /orders` 重渲染。
- 面板头部一个「刷新」按钮。

## 数据流

```
init() (purchase.js, 一次)
  └─ initPurchaseOrders(#purOrders)
       └─ fetch GET /purchase/orders → render 表格
行内操作 (事件委托)
  ├─ 标到货 → 展开 date 编辑器 → 确认 → POST /arrival → 重新 fetch+render
  ├─ 改期   → 展开 date 编辑器 → 确认 → POST /update  → 重新 fetch+render
  └─ 作废   → confirm() → POST /void → 重新 fetch+render
```

## 安全 / 转义（必须项）

`GET /orders` 的 `supplier_name` / `source_file` / `status` 及错误 `msg` 一律当**不可信文本**：

- 字段拼进 HTML 走 `shared.js` 的 `esc` / `escapeAttr`。
- 错误 `msg` 用 `textContent` 渲染（或 `esc` 后插入），不裸拼。

## 错误处理

接口返回 `{ok:false, msg}` 时，在面板内显示红条（复用 `pur-status` 风格）。覆盖：
- 400：误带 arrival_date / 坏日期。
- 404：缺单（理论上不会，列表刚拉的；但要兜住）。
- 网络/500：通用「操作失败」+ 保留原列表。

## 测试 / 验证

无 JS 单测框架 → 本地手动验证为主（符合「前端改动本地测试后再 push」）。

1. `dev.ps1` 起本地服务，浏览器开采购页。
2. 走全路径：标到货（默认今天 + 改日期）/ 改期 / 作废 / 误带 arrival_date 的 400 红条。
3. **布局回归（重点）**：在三种页面状态下都确认 `#purOrders` 可见且不挤坏 02/03/04：
   - 空态（未上传采购 Excel）
   - 已解析态（02 有数据）
   - 新条码面板展开态（03 显示）
4. Playwright 截图核对暗色 / 亮色主题。
5. 验证通过再走分支 squash merge（push main 触发生产部署，由用户手动执行）。

## 开放项

- 「显示已作废」开关：暂不做，void 单灰显在列表里即可。要了再加。
- 金额格式：千分位 + €，沿用页面现有数字风格。
