# ADR-0002: 预测模型选择路由 — 实证标定的决策树

> **Status**: Proposed（待用户批准）
> **Date**: 2026-06-11
> **作者**: Fable 5（标定数据 = 本地 PG 镜像 2026-06-10，backtest runs 36-49）
> **关联**: ADR-0001（补货策略，horizon 列消费方）、`docs/backtest-results-2026-05-19.md`、
> `tools/calibrate_model_routing.py`（标定脚本，类别变更时重跑）

## 要回答的问题

"什么时候该信哪个模型、Croston/SBA/TSB 各自适用的 ADI×CV² 区间在哪" ——
把这套判断固化成查表可执行的路由，新增 SKU 类别时不用重新推理。

## 实证发现（先于决策，全部可由标定脚本复现）

### F1. 本组合 99% 落在间歇侧 —— 文献的 ADI×CV² 象限在这里不分流

23,516 个可算 SKU（非零销售周 ≥5、跨度 ≥20 周）：

| 象限（Syntetos-Boylan 切点 1.32 / 0.49） | 占比 |
|---|---|
| lumpy（间歇+高变异） | **55.7%** |
| intermittent（间歇+低变异） | **43.3%** |
| erratic | 0.9% |
| smooth | 0.1% |

ADI 分位：p10=1.88 / p50=3.64 / p90=8.94 —— **整个组合都在文献切点 1.32 之上**
（中位 SKU 每 3.6 周才卖一次）。教科书决策树在这里退化成单分支。

**这是本 ADR 最重要的结论：模型选择的真实驱动不是 ADI×CV² 象限，
而是 ① 用途（点预测 vs 尾部分位）和 ② 数据可得性（base_demand 序列有无）。**
（论文注：这是有数据支撑的负结果——"文献方法在真实长尾零售组合上失效"，
配 F2 的象限内交叉表可直接写进第 5 章。）

### F2. 象限内模型排序跨象限一致 —— 赢家不随象限变

intermittent / lumpy（合计 99%）× base_demand 视图，最新 runs：

| 模型 | medMASE (int./lumpy) | avgCov@98 (int./lumpy) | 角色 |
|---|---|---|---|
| NaiveMean4W | **0.949 / 0.930** ⭐点最准 | 0.894 / 0.882 ✗尾部最差 | 点基准 |
| EmpiricalQuantile | 0.977 / 0.969 | **0.974 / 0.970** ⭐唯一近标称 | 补货主力 |
| CrostonSBA | 0.984 / 0.974 | 0.933 / 0.941 | 间歇均衡 |
| HoltWinters / LinearTrend / NaiveSeasonal | 全面落后 | | 已退役/baseline |

erratic（n=38）里 CrostonSBA/EmpQuant 领先，排序同向。smooth n<20 无法评。

### F3. wholesale 代理子集：CrostonSBA 点最准，EmpQuant 点劣于 naive

非 retail/mixed 的活跃 SKU（'all' 视图有回测分的，n=27）：

| 模型 | medMASE | avgCov@98 |
|---|---|---|
| **CrostonSBA** | **0.966** | 0.930 |
| NaiveMean4W | 0.978 | 0.909 |
| EmpiricalQuantile | 1.050 ✗劣于 naive | 0.973 |

样本薄（多数 wholesale 不满 20 非零周进不了回测）→ 方向性成立、置信中等，
路由后随数据积累重验。

### F4. 生命周期分类退化确诊：97.0% unclassified、seasonal = 0

active 30,577 个 SKU：unclassified 29,647（97.0%）/ declining 509 / stable 292 /
new 47 / **seasonal 0**。

**根因**：`categorizer.py` 生命周期阈值是为平滑序列设计的，撞上 F1 的间歇组合——
- `stable` 要求 ≥50% 周有销售；组合中位 ADI 3.64 ⇒ 典型活跃占比 ~27%，结构性不可达
- `seasonal` 要求 ACF(52)>0.5 + 两年峰周重叠；间歇序列 ACF 被零周稀释，0 命中
- `declining` 要求最近 4 周有销量且斜率<0；间歇 SKU 最近 4 周常为全零 → 直接出局

**范围注**：生命周期分类不参与预测路由（路由用 sku_type，分布健康：
retail 85.8% / wholesale 13.2% / mixed 1.0%，2026-05 口径）。
阈值重标定是独立工作，本 ADR 只立检测（D5），不修。

## 决策

### D1. 路由表（表驱动单源，代码 = `app/services/forecast.py::ROUTING`）

| sku_type | 训练序列 | 周模型 | horizon 列 | 准入条件 |
|---|---|---|---|---|
| retail_dominant / mixed | base_demand（剔大单 + 剔缺货周） | EmpiricalQuantile | bootstrap（ADR-0001 D5） | ≥13 周 |
| **wholesale_only（新增）** | weekly_demand_series（原始+退货归并+剔缺货周） | **CrostonSBA** | bootstrap（同上） | ≥13 周 **且 非零周 ≥5** |
| dying | — 不预测（4-baseline 回测：强出预测 bias +0.89） | | | |
| unclassified | — 不预测（新品冷启动 = 论文三档路线图，另案） | | | |

wholesale 不剔大单：大单就是它们的需求本体，base_demand 的剔除逻辑对其无意义。
非零周 ≥5 闸：CrostonSBA 的 interval 估计在 <5 个观测点上是噪声（同标定脚本准入口径）。

### D2. retail/mixed 维持 EmpiricalQuantile 单模型

NaiveMean4W 点准度好 ~4%（F2）但 Cov@98 差 8-9 个百分点。补货消费的是尾部，
覆盖率是硬指标；不为 4% 的点增益引入双模型维护。NaiveMean4W 的点优势记录在案，
未来若做"销量趋势展示"类功能再议。

### D3. wholesale 的周字段走 CrostonSBA，horizon 列照走 bootstrap

CrostonSBA 的 p98 是 μ+z·σ 正态近似（已知尾部弱，回测 Cov 0.930）。但补货量
消费的 p50_h/p98_h 由 `horizon_quantile` 直接对原始序列 bootstrap —— **模型无关**，
不受正态近似拖累。置信分层因 missing_backtest 自然落 low，诚实不装。

### D4. TSB 不引入（用户问题的直接回答）

TSB（Teunter-Syntetos-Babai）相对 Croston/SBA 的增量价值 = 处理需求消亡
（每期更新需求概率，库存退役场景）。本系统的 `dying` 闸（13 周无销 → 不预测）
已经用更粗暴但更彻底的方式吸收了这个场景 —— TSB 的渐进衰减预测 vs 我们直接停
（且回测证明强行预测 dying 引入 +0.89 bias）。**结论：TSB 的适用区间被 dying 闸
覆盖，不实现**。若未来 dying 闸改为渐退（如清仓定价需要残值预测），TSB 是首选，
此判断记录在案。

### D5. 退化检测（红线 RL-11，接 cron 巡检）

1. **预测覆盖率塌方**：`forecast_output 行数 / active SKU 数 < 15%` → 告警。
   （路由上线后预期 ~25%+；跌破说明分类或路由把 SKU 批量甩出了预测。）
2. **sku_type 垄断**：forecast_output 里任一 sku_type 占比 > 97% → 告警。
   （wholesale 路由上线后 retail 占比应 < 97%；回到 97%+ = wholesale 腿断了。）
3. 生命周期分类的 97% unclassified 是**已知未修**状态（F4），不挂告警
   （挂了就是永远红的噪声）；重标定完成后由其 plan 自带告警阈值。

### D6. 标定可再生

`tools/calibrate_model_routing.py` 固化本次分析（象限分布 + 象限×模型交叉表 +
wholesale 子集对比）。**任何新增 SKU 类别 / 改 categorizer 阈值 / 换主力模型的
PR，先重跑此脚本，把输出贴进 PR 描述** —— 这就是"以后直接查表，不用重新推理"
的机制本体。

## 后果

**正面**：wholesale_only（13.2% 的有类型 SKU）从无预测 → CrostonSBA + bootstrap
horizon，补货页不再用 `销速×1.5` 拍系数；决策树文档化 + 标定脚本可再生；
退化有自动告警。

**负面/风险**：wholesale 多数无回测分 → 置信全 low（诚实但用户会看到一片 low，
PR 里要说明）；CrostonSBA 周字段与 bootstrap horizon 列来自不同估计器，
理论上可能出现 p98(周) 与 p98_h(H周) 不协调的展示（量级差异本来就该存在，
红线 RL-5 的单调不变量仍守住）。

## 实施验证（2026-06-11，本地 PG 镜像实跑）

- 路由生效：retail 6,170（EmpQuant）/ mixed 74（EmpQuant）/ **wholesale 39（CrostonSBA）**
- **wholesale 收益被 dying 闸压低**（量化）：活跃 SKU 最后销售距今 13-26 周的
  "边际带"有 **1,199 个** —— `_DYING_WEEKS=13` 对批发节奏（组合 ADI p90≈8.9 周，
  批发更长）偏紧，批发 SKU 一个正常的下单间隔就会被误判 dying 甩出预测。
  **下一步建议（不在本 PR）**：dying 阈值按 sku_type 分型（如 wholesale 26 周），
  改前按 D6 重跑标定脚本。
- **顺手修复**：full refresh 现在清理本轮不再够格 SKU 的旧行（此前转 dying /
  路由变更后的僵尸预测行会永久残留并被补货页消费，本地镜像实测残留 441 行）。

## 备选方案（已否决）

| 方案 | 否决理由 |
|---|---|
| 按 ADI×CV² 象限路由 | F1/F2：本组合 99% 单侧、象限内排序一致，树无信息量 |
| retail 双模型（Naive 点 + EmpQuant 尾） | 4% 点增益不值双模型维护成本（D2） |
| 引入 TSB | dying 闸已覆盖其适用场景（D4） |
| wholesale 也用 EmpiricalQuantile | F3：点准度劣于 naive（medMASE 1.050） |
| 顺手重标定生命周期分类阈值 | 与路由正交，独立 plan 做（F4 范围注） |
