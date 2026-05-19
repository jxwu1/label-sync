# 2026-05-19 全量回测结果（累积训练 + HW 加速后）

> 修了 `walk_forward_backtest` 累积训练 + `HoltWintersModel` 加速 (`use_brute=False` + `maxiter=50`) 后，跑 6 模型 × 2 view = 12 run（id 36-47），4279 SKU (base_demand) / 4351 SKU (all)。
>
> 配套 commit: `5b64d80`（算法 fix）+ 本批 runs。

## 指标对照表

### base_demand view（n=4279，补货关注，已剔大单 + 归并退货）

| Model | run_id | MAPE↓ | MASE↓ | Bias | Cov@98↑ | runtime |
|---|---:|---:|---:|---:|---:|---:|
| **EmpiricalQuantile** | 44 | **0.814** ⭐ | 0.978 | 0.296 | **0.972** ⭐ | 86.5 s |
| CrostonSBA | 42 | 0.828 | 0.977 | 0.217 | 0.938 | 48.9 s |
| HoltWinters | 46 | 0.954 | 0.993 | 0.352 | 0.926 | 13322.5 s |
| NaiveMean4W | 36 | 0.959 | **0.936** ⭐ | 0.016 | 0.886 | ~ 44 s |
| LinearTrend12W | 40 | 1.046 | 1.045 | 0.013 | 0.904 | 63.0 s |
| NaiveSeasonal52W | 38 | 1.062 | 1.052 | 0.281 | 0.947 | ~ 39 s |

### all view（n=4351，含批发大单原始信号，污染高）

| Model | run_id | MAPE↓ | MASE↓ | Bias | Cov@98↑ | runtime |
|---|---:|---:|---:|---:|---:|---:|
| EmpiricalQuantile | 45 | 0.823 | 0.967 | 0.383 | 0.971 | 81.8 s |
| CrostonSBA | 43 | 0.838 | 0.962 | 0.237 | 0.942 | 42.5 s |
| HoltWinters | 47 | 0.982 | 0.989 | 0.437 | 0.931 | 13689.2 s |
| NaiveMean4W | 37 | 0.983 | 0.933 | 0.019 | 0.883 | ~ 44 s |
| LinearTrend12W | 41 | 1.086 | 1.046 | 0.013 | 0.904 | 57.4 s |
| NaiveSeasonal52W | 39 | 1.090 | 1.049 | 0.367 | 0.949 | ~ 45 s |

## 主要发现

### 1. 累积训练 fix 确实见效

昨晚 NaiveSeasonal52W 和 EmpiricalQuantile 的 med_MAPE / med_MASE / avg_Bias 完全相同
(0.852 / 0.937 / 0.013) —— 两者实际都退化成 `mean(13)`。

改累积训练后：

| Model | 昨晚 (run 25/28, win=13 滑动) | 今天 (run 38/44, 累积) |
|---|---|---|
| NaiveSeasonal52W base_demand | MAPE 0.852 / Cov@98 0.912 | **MAPE 1.062 / Cov@98 0.947** |
| EmpiricalQuantile base_demand | MAPE 0.852 / Cov@98 0.924 | **MAPE 0.814 / Cov@98 0.972** |

NaiveSeasonal52W 真用上 lag-52 后 MAPE 反而更差（季节信号弱、lag-52 高方差）。
EmpiricalQuantile 拿到更多数据后 p98 覆盖率显著上升（0.924 → 0.972）。

### 2. EmpiricalQuantile 是新冠军（补货场景）

- base_demand: MAPE 0.814 + Cov@98 0.972，两项都拿第一
- 单 SKU 算力 ~20 ms，跑 4279 SKU 86 s
- 真正吃到 "wholesale / 间歇序列尾部" 的特征 —— 直接经验分位数比 mu+z·σ 正态近似更稳

### 3. HoltWinters 性价比最差

- 算力 ~3 s/SKU（base_demand 4279 SKU 跑 3h42m）
- 所有指标都被 EmpiricalQuantile 压制（MAPE 0.954 vs 0.814，Cov@98 0.926 vs 0.972）
- 即使序列 ≥ 104 周走季节项，statsmodels 收敛在这批 SKU 上没拿到优势
- **建议**：生产链路退役，仅保留 baseline 库做对照基线

### 4. NaiveSeasonal52W 是真的烂

- MASE > 1 ⇒ 比 lag-1 naive 还差
- 这批 SKU 的年同比信号弱，单独 lag-52 抓不到稳定模式
- 留作 baseline 即可

### 5. MASE 第一名是 NaiveMean4W 但 Cov@98 倒数第一

- MASE 0.936（最低）vs Cov@98 0.886（最低）—— 点估计准但分布尾部估计差
- 因为 4 周窗口太短，σ 过小 → p98 = μ + 2.054·σ 偏低 → 实际值经常打穿
- 不适合做补货上限（需要 p98 cover）

## 推荐生产配置

**Primary model**: EmpiricalQuantile
**Fallback**: CrostonSBA (间歇序列 fallback，比 EmpQuant 略差但 bias 更小)
**Baselines for reference**: NaiveMean4W / NaiveSeasonal52W / LinearTrend12W
**Deprecate**: HoltWinters

## base_demand vs all view

base_demand 几乎全方位优于 all（MAPE 略低、Bias 显著低）：

| Metric | base_demand | all | Δ |
|---|---:|---:|---:|
| EmpQuant MAPE | 0.814 | 0.823 | +1.1% |
| EmpQuant Bias | 0.296 | 0.383 | +29% |
| CrostonSBA Bias | 0.217 | 0.237 | +9% |

验证了 base_demand pipeline（剔大单 + 归并退货）的清洗价值：
all view 的正偏（高估）显著大于 base_demand。

## 待办

参见 `docs/data-analytics-overview.md`:

- §9.3 SKU 来源分群（FOREIGN vs CN filter，国外货专属指标）—— 下一步
- §3.7 forecast_output 表 + 每日刷新 —— 后续
- §4.x Dashboard 集成（SKU 详情页预测卡片 + 列表页 MAPE 排序）—— 后续
