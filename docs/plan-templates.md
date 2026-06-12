# Plan 模板与反例库

> **Date**: 2026-06-12（P4 判断层产出，作者 Fable 5）
> **用法**: 接到三类常见任务时，复制对应模板骨架到
> `docs/superpowers/plans/YYYY-MM-DD-<名字>.md`，逐项填实。模板里的
> 【易错】标注全部来自本仓库真实事故（反例库 E 编号，附 commit 实证）——
> 不是泛泛的最佳实践，是这个项目真摔过的跤。
> **配套**: `docs/system-mental-model.md`（改 X 波及表）、AGENTS.md Review 红线、
> `docs/adr/`（决策依据）。写 plan 前先查这三处，plan 里直接引用编号。

---

## 通用写作守则（从 37 份历史 plan 提炼）

1. **每步带可执行 verify**。"让它能跑"不是 verify；"pytest tests/test_x.py 退出码 0"是。
2. **spec/ADR 先行，review 收紧后再动手**。stockout spec 一轮 review 收紧了
   周一唯一口径/series 契约/负库存阈值三处（f0ccaa1）——这些含糊点若进了
   实现，就是三个 bug。数值类任务先写 ADR（备选方案 + 否决理由），用户批准
   Accepted 再实施。
3. **批次独立 commit，可单批回退**（refactor plan Phase 2 模式：每批移动后
   pytest，红了 reset 该批）。
4. **工时估算 ×3 规则**：refactor Phase 2 原估 1-2 小时，复审修正为 1-2 天
   留 3 天 buffer。涉及"全仓库改 import / 全链口径"的任务默认乘 3。
5. **完成定义含线上/真机验证**，不止测试绿：PDA 系列 6 个 fix（#25-30）全是
   "模拟器绿、真机挂"；前端改动本地 `dev.ps1` 浏览器验证后再 push。
6. **声明影响面**：动分类/清洗/公式的 plan 必须有"波及与失效声明"一节
   （查心智模型 §五表填）。

---

## 模板 T1：新增 forecasting 模型

```markdown
# Plan: 新增 <模型名> 预测模型

## 前置检查（不过门不动手）
- [ ] 重跑 `tools/calibrate_model_routing.py`，确认新模型有目标 SKU 段位
      （红线 B2；没有目标段位 = 这个模型没有存在理由，停）
- [ ] 读 ADR-0002 备选方案表——你要加的模型可能已被否决过（如 TSB），
      先确认否决理由是否已失效
- [ ] 查 system-mental-model §五 "ROUTING 表 / 新增模型" 行

## 步骤
1. 模型类实现（纯 numpy，实现 ForecastModel Protocol: fit/predict）
   → verify: 单测覆盖 空/单元素/常数/间歇/大单 序列 + RL-5 不变量
     （mu/sigma/p50/p98 ≥ 0, p50 ≤ p98）
2. 注册 BASELINES，跑 walk-forward 对比 run（先当 baseline，不接路由）
   → verify: backtest run 入库；与 EmpiricalQuantile 同视图对比表产出
3. 决策闸：分 SKU 段位赢了才继续；输了写进 ADR"已评估未采用"然后停
   → verify: ADR-0002 增补 D 决策（或新 ADR），标定输出贴 PR
4. 接 ROUTING + refresh 路径（定义准入闸，参照 wholesale 非零周 ≥5 模式）
   → verify: refresh 后 forecast_output.model_used 正确；
     僵尸行清理覆盖路由变更；RL-11 巡检阈值复核（垄断/覆盖率边界变了吗）
5. 置信分层 join 检查（耦合 C8：分层只 join EmpQuant run）
   → verify: 新模型 SKU 的 tier 行为是显式决定的
     （接受 missing_backtest→low，或扩 join——别让它隐式发生）
6. 数值守护网全绿
   → verify: redlines + properties + golden 三套测试 + ./test.ps1

## 波及与失效声明
- 查心智模型 §五；本 plan 影响：____
```

【易错】E2（sqlite 绿 PG 挂）、E5（多处实现漏同步）、回测先行原则
（决策记录：没 evaluator 就调模型 = 盲调）、C8 分层错位。

---

## 模板 T2：新增/修改 replenishment 策略

```markdown
# Plan: <策略名> 补货策略

## 前置检查
- [ ] 读 ADR-0001 全文，特别是备选方案否决表——"新策略"八成被否决过，
      先确认否决理由（库存可见性周批量 / 正态近似尾部差 / YAGNI）是否变了
- [ ] 红线 A1-A11 逐条过一遍，标出本次会触碰的条目
- [ ] 查 system-mental-model §三 _restock_recommendation 假设清单

## 步骤
1. ADR 先行：D 编号决策 + 备选否决 + redlines 清单增补
   → verify: 用户批准 status: Accepted（注意：spec「状态」字段不预写结论）
2. 纯函数实现（决策逻辑不碰 DB，DB 输入由调用方注入）
   → verify: 手算预期值的红线样例测试（test_replenishment_redlines.py 增补）
3. property 不变量扩展（非负/单调/凑整/在途覆盖是否仍然全部成立）
   → verify: tests/test_replenishment_properties.py hypothesis 无反例
4. golden 基线更新
   → verify: 旧基线变红（证明改动生效）→ PR 描述解释数值为什么该变 →
     新基线绿（红线 D2：无解释的基线更新 = 让测试迁就 bug）
5. 接 summary/补货页（注意耦合 C9：forecast 刷新后必须 summary 刷新）
   → verify: 本地 dev.ps1 + pull_prod_db 真数据浏览器验证后再 push
6. 退化监控：新策略有什么 RL-9/10/11 式的运行时退化模式？
   → verify: 巡检函数 + 单测，接 alerts 通道

## 波及与失效声明
- 推荐量变化幅度预估 + 用户沟通口径（ADR-0001 教训：推荐量普遍下降会让
  用户觉得"系统变保守了"，要在 PR 和系统页解释）
```

【易错】E1（周分位 × 系数复发 = 红线 A4 直接 reject）、E4（静默截断/丢弃——
只标记不截断）、E6（负库存等双口径只改一处）、E8（物化不刷新）。

---

## 模板 T3：扩展 SKU 分类维度 / 改分类阈值

```markdown
# Plan: <分类维度/阈值> 调整

## 前置检查（这是全系统传染面最大的改动类型）
- [ ] 把 system-mental-model 耦合 C3（分类→视图→预测→回测单向静默传染）
      和 C5（sku_type 三处独立计算）读两遍
- [ ] 跑 `tools/calibrate_model_routing.py` 留 before 分布底片

## 步骤
1. 纯函数改动（classify_sku_type_from_docs / 阈值常量）
   → verify: 单测含边际带样例（阈值两侧 ±1 的 SKU 各一个）
2. bulk 路径同步（base_demand_views_bulk 内联 _classify）
   → verify: test_bulk_matches_per_sku_view 一致性测试过
3. 回测路径确认（backtest._build_series 走 base_demand_view，自动继承？确认）
   → verify: 同一 SKU 三路径分类一致的测试
4. 重跑标定脚本出 after 分布，before/after 对比贴 PR（红线 B2/B3）
   → verify: RL-11 阈值复核——新分布下垄断/覆盖率告警边界还对吗
5. 失效声明 + 关键回测 run 重跑
   → verify: ADR 引用值刷新；历史 run 与新口径不可比的地方标注

## 波及与失效声明
- 本次阈值变动使 ____ 个 SKU 换类（标定脚本输出）；
  历史回测 run ≤ #__ 与新口径不可比
```

【易错】E3（阈值不分型：dying 13 周把 1,199 个活批发 SKU 误判死，#43 修成
类型感知）、E5（三处实现漏同步）、F4 教训（拍脑袋阈值 → 97% unclassified
退化，检测规则要随阈值一起立）。

---

## 反例库（全部有实证，按失败模式编号）

> 写 plan / review 时按编号引用。新事故 → 追加条目，附 commit。

- **E1 周分位 × 系数**：`p98×8`、`×13` 当多周需求——分位数不可线性相加，
  系统性高估 2-3 倍（#41 修正，中位降到旧值 29.7%）。任何"周值 × 周数"
  形态默认有罪（红线 A4）。
- **E2 sqlite 绿、PG 挂**：GROUP BY 缺列 PG 报 GroupingError（16845a2）、
  硬删员工撞 PG 外键 500（7d37ce5）、测试裸 sqlite3 seed。防线 = CI 双矩阵 +
  合并前 `./test.ps1`；但**写 SQL 时就该想两个方言**，别等 CI 兜。
- **E3 阈值不分型**：dying 统一 13 周把活批发判死（批发 ADI p90≈9 周，
  13 周只是正常下单间隔），1,199 个边际带 SKU 被甩出预测（#43 修成
  13/26 类型感知）。教训：一刀切阈值在异质群体上必出系统性误判。
- **E4 静默丢弃/截断**：完全无历史的"幽灵"产品被定价表静默丢弃（234d16e）。
  立法 = RL-6：异常只标记不截断、不静默——丢弃/截断会掩盖上游 bug。
- **E5 双实现漂移**：同一语义多处实现，改一处漏一处——bulk SQL 与 Python
  路径对空单号 NULL/'' 的分组不一致（7f7e51a review round3）；sku_type
  三处计算（C5）；barcode↔model 两座桥（C2）。防线 = 一致性测试 +
  心智模型登记，最好收敛单源。
- **E6 口径联动漏改**：KPI 的紧急/关注/充足没排除已下单+已跳过，与决策
  回流口径不一致（dc18c26）；负库存判定 restock/stockout 必须同步（RL-7）。
  改任何"口径"先 grep 同语义的所有消费点。
- **E7 环境差异只在生产爆**：Linux 无中文字体 PDF 方块（12bf0bd）、PDA
  真机扫码 document 捕获收不到键（#25-30 连环 6 修）、Flask 模板缓存 +
  僵尸 :5000 端口让前端改动"看起来没生效"。防线 = 真机/容器内验证进
  完成定义。
- **E8 缓存/物化不刷新**：导入后不清缓存读旧数（7f7e51a）；forecast 刷新
  不接 summary 刷新 = 补货页旧推荐（C9）。新增任何缓存/物化时，**失效
  路径与写入路径同 PR 落地**。
- **E9 spec 口径含糊直接进实现**：stockout spec 一轮 review 收紧周一唯一
  口径/series 契约/负库存阈值三处（f0ccaa1）。口径类含糊在 spec 阶段
  一句话就能定死，进了实现就是跨模块不一致。
- **E10 生产长任务期间 push main**：Coolify 监听 main 任何 push 即 redeploy，
  会杀掉飞行中的后台任务（含 docs 改动）。长任务窗口积压改动留分支。
- **E11 飞行任务 vs 大重构冲突**：Phase 2 移 40+ 文件会让飞行中 backtest
  进程崩溃后找不到模块——refactor plan 因此立了执行前置条件。大重构前
  先清点"现在天上飞着什么"。
- **E12 工具链版本漂移**：ruff 不钉版本 → 新版规则更严，hook/CI 对既有
  代码大量误报（c6c5aa3 钉死 + hook 降级只读告警）。lint/format 工具
  必须 pin 且本地=CI 同版。
