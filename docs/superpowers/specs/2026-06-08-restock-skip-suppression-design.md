# 补货页 skip 抑制（决策反馈回流）

**日期:** 2026-06-08
**分支:** `feat/restock-skip-suppression`（待开）
**状态:** 设计已批准，待写实施计划
**来源:** Codex 审查 backlog 第 2 期「决策↔算法断线」中的 C（决策反馈回流）；本期只做 C 的 skip 抑制子集，stale 高分看板留 backlog。

## 背景

补货决策已经在写但没在读。现状（核对代码）：

- 标「✓ 已下单」→ 进 `state.ordered`（localStorage，30 天过期）→ 默认隐藏该行 + 后端记 `ordered/overridden`。
- 标「✗ 不进」→ **只发后端记 `skipped`+reason，前端什么都不留** → 下周该 SKU 照样高分置顶尖叫。
- 后端 `GET /restock/decisions/{recent,stats,stale}` 三端点已存在但**前端零调用**；urgency 评分算法（`restock_calc.py`）完全不读 `restock_decisions`。

痛点：标了「不进」是个真实判断（供应商断货 / 客人未确认 / 等下次活动），但这个判断没有任何回流，下一周列表把同一个 SKU 又顶到最前面，操作员每周重复否决。

## 目标

把已经写进 `restock_decisions` 的 skipped 决策**读回来影响下一次列表展示**：标「不进」后默认隐藏一段时间，到期或新进货后自动回到正常候选。这就是"反馈回流"——已写入 DB 的决策影响下一次列表。

## 非目标（YAGNI）

- **不改评分算法**：`restock_calc.py` 不动，urgency 仍按真实数据计算。抑制是"展示/决策层过滤"，不是"模型认为不紧急"。
- **不改 DB schema**：复用现有 `restock_decisions` 表，不加列、不迁移。
- **不做 stale 高分看板 / 决策统计面板**：留 backlog（C 的另一半）。
- **不做 UI 可配置的抑制天数**：14 天是业务规则，写后端常量 `SKIP_SUPPRESS_DAYS = 14`，不暴露成 query 参数 / 设置项。用真实跑一两轮后再决定调 7/14/30。
- **不碰 `ordered`（已下单）逻辑**：它仍走 localStorage，本期不动。

## 范围

- 后端：`app/services/restock_decisions.py`（加 `list_suppressed`）+ `app/routes/restock.py`（加 `GET /restock/decisions/suppressed`）。
- 前端：`static/js/restock.js`（拉 suppressed → `state.suppressed`、过滤隐藏、`已跳过` band、tag 渲染）+ `templates/partials/_page_restock.html`（band 按钮）+ `static/css/components.css`（`已跳过` tag 样式，若现有 tag 不够用）。
- 测试：`tests/` 加 `list_suppressed` 单元测试（纯后端逻辑，可执行覆盖）。

## 设计

### 后端：`GET /restock/decisions/suppressed`

无 query 参数。`SKIP_SUPPRESS_DAYS = 14` 为模块常量。

**`list_suppressed(session) -> dict[str, dict]` 规则**（每 barcode 一条判定）：

1. 取每个 barcode **最近一条**决策（按 `decided_at` 倒序，每 barcode 取第一条）。
2. 该 barcode 进入抑制集，当且仅当**全部**满足：
   - 最近一条决策是 `skipped`（若最近是 `ordered`/`overridden` → 不抑制，自动处理"先 skip 后又下单"）；
   - `skipped_at` 在 14 天内：`(today - skip_date).days < SKIP_SUPPRESS_DAYS`（`skip_date = decided_at[:10]`）；
   - 没有后续新进货：该 barcode 的 `MAX(InventoryEvent.event_at where event_type='purchase')` **不晚于** `skip_date`（按日期粒度比较，`purchase_date > skip_date` 即解除）；无任何 purchase event 也算"没有后续进货"→ 维持抑制。
3. 返回：

```json
{
  "ok": true,
  "items": {
    "<barcode>": { "skipped_at": "2026-06-05 14:30:00", "reason": "供应商断货", "days_left": 9 }
  }
}
```

- `days_left = SKIP_SUPPRESS_DAYS - (today - skip_date).days`（必 ≥1，否则该行已不在抑制集）。
- `reason` 取最近那条 skipped 决策的 `reason`（可能为 null）。

**取数实现要点**：
- 决策侧：一条 SQL 拉近 ~30 天内所有决策（缩小扫描），Python 端按 barcode group 取最近一条；或用窗口/子查询取每 barcode 最新。被跳过的 barcode 量小，Python 端聚合够用。
- 进货侧：仅对候选 barcode 集 `select product_barcode, max(event_at) ... where event_type='purchase' and product_barcode in (...) group by product_barcode`，一次查回。
- 日期比较统一切到 `[:10]`，规避 `event_at`(YYYY-MM-DD) 与 `decided_at`(YYYY-MM-DD HH:MM:SS) 格式差异。

### 前端：过滤 + band + tag

1. **取数**：`load()` 里在拉 `/analytics/list` 之后，并行/串行拉 `GET /restock/decisions/suppressed` → 存 `state.suppressed`（`{barcode: {skipped_at, reason, days_left}}`）。拉失败兜底为空对象（不阻断主列表）。
2. **乐观隐藏**：`markSelectedSkipped` / `markSingleSkipped` 记录后端成功后，本地把这些 barcode 加进 `state.suppressed`（`skipped_at=now, reason, days_left=14`）→ `render()` 立刻隐藏，无需等下次 load。
3. **过滤**：`_filterPredicate` 加规则——
   - 默认（band ≠ `skipped`）：若 `barcode in state.suppressed` → 隐藏。
   - band = `skipped`：只显示 `barcode in state.suppressed` 的行（类似现有 `flagged` band 的"只看勾选"）。
   - 进货提前解除已由后端算进 `state.suppressed`（不在集里就不隐藏），前端不再重复判断 last_purchase；与 `ordered` 的前端 `autoClearOrderedByPurchase` 不同（那是 localStorage 客户端真源，这是 DB 真源）。
4. **band 按钮**：band 行（现有 `全部/紧急≥70/关注/充足/已标记`）加一个 `已跳过`。点击切到只看抑制项。band 计数可显示当前抑制数。
5. **tag**：抑制行（在 `已跳过` band 下可见）行内显示 `已跳过` tag，`title` = `原因 + 跳过时间 + 剩余 N 天`（复用现有 `.rs-tag` 体系，必要时加 `.rs-tag--skip`）。

### 数据流

```
标「不进」+reason
  → POST /restock/decisions/batch (decision=skipped) [既有]
  → 乐观写 state.suppressed[bc] → render 隐藏
  ───（下次进页 / 刷新）───
load()
  → GET /analytics/list (主列表) [既有]
  → GET /restock/decisions/suppressed → state.suppressed
  → _filterPredicate 默认隐藏 suppressed 行
  → band「已跳过」可翻出, 行显示 tag(原因/时间/剩余天数)
  ───（14 天到期 或 新进货 last_purchase_at>skip_date）───
后端 list_suppressed 不再返回该 barcode → 自动回到正常候选
```

### 边界 / 错误处理

- suppressed 端点失败 → 前端 `state.suppressed = {}`，主列表照常（降级为"不抑制"，不阻断）。
- 同一 barcode 多次 skip → 只看最近一条（最近 `decided_at`）。
- skip 后又 order（最近决策是 ordered/overridden）→ 不抑制（且 `ordered` 还会另行隐藏）。
- 决策历史**永不因解除而删除**——解除只是不再进抑制集；`restock_decisions` 全量保留，将来 stale 看板 / 算法体检仍可用。
- 无 purchase event 的 barcode → 视为"无后续进货"→ 维持抑制（不因缺进货数据误放出）。

## 测试 / 验证

- **后端单元测试**（`tests/`，可执行）覆盖 `list_suppressed`：
  1. 最近是 skipped 且 14 天内、无进货 → 抑制，`days_left` 正确。
  2. skipped 超过 14 天 → 不抑制。
  3. skipped 后又 ordered（最近是 ordered）→ 不抑制。
  4. skipped 后有新 purchase event（`event_at > skip_date`）→ 不抑制（提前解除）。
  5. 同日 purchase（`event_at == skip_date`）→ 仍抑制。
  6. 同 barcode 多条 skipped → 取最近一条的 reason / skipped_at。
- **前端人工走查**（本地 `dev.ps1` + 灌数据或合成 sku_summary + 写几条 restock_decisions）：标「不进」立刻消失；`已跳过` band 能翻出 + tag 显示原因/剩余天数；改某条 decided_at 到 15 天前 → 重新出现在主列表。
- 全量 `pytest tests/` 通过。

## 验收标准

- [ ] `GET /restock/decisions/suppressed` 返回 `{ok, items:{barcode:{skipped_at,reason,days_left}}}`，14 走后端常量不暴露 query。
- [ ] 今天标「不进」→ 主补货列表（默认 band）立刻看不到该 SKU。
- [ ] 进「已跳过」band → 看到它 + tag（原因 + 跳过时间 + 剩余天数）。
- [ ] 第 15 天（skipped 超 14 天）→ 自动重新出现在正常候选。
- [ ] 期内该 SKU 有新进货（`purchase event_at > skip_date`）→ 提前重新进入正常判断。
- [ ] 最近决策是 ordered/overridden 的 barcode 不被抑制。
- [ ] 决策历史不因解除/到期删除（`restock_decisions` 保留）。
- [ ] `restock_calc.py` 评分算法与 DB schema 均未改动。
- [ ] `list_suppressed` 单元测试全过 + 全量 `pytest tests/` 通过。
