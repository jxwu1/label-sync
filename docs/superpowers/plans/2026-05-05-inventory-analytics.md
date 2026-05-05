# 阶段 4 + 阶段 5：进销存事件 + 销售分析（中和版）

> **起草**：2026-05-05
> **方向**：把 4 年 ERP 历史数据接入 → 客户端拆分展示 → 高置信度自动 4 类分类 → 老外客人模块。**不**做：7 类决策树、全自动化预测、反馈循环 UI（v1）。

---

## 决策日志（这一轮讨论锁定）

1. **批发场景**：营业模式 = 批发市场，4 大主品类（渔具 / 汽车 / 家用 / 宠物）+ 33+ FL 子家族。源 ERP 分类系统**仅作参考**，不照抄。
2. **数据量**：4 年历史 + 5 万 SKU + 几十到几百万销售/采购事件。
3. **客户两类**：
   - 中国客户：单笔大、频率低（几个月一次）
   - 老外客户：单笔小、频率高（每周/月）
   - 识别方式：客户名包含中文字符 = 中国人；包含希腊字符 = 老外；混合 = 待人工归类
4. **分类策略**：**中和版**——只自动判 4 类高置信度类别（稳定 / 衰退 / 新品 / 季节性），其余归"未分类"由用户手工打 manual_category 标签。
5. **客户端拆分仅展示，不参与算法**（v1）。等用户用一阵子后再下沉到算法层（v1.1+）。
6. **Prophet 预测 / 反馈循环 UI / 7 类决策树** —— 全部 v2 议题。v1 不做。
7. **xls 伪装格式**：源 ERP 导出的 .xls 实为 HTML，用 `pandas.read_html` 解析。下载慢的优化（直连后端 endpoint）作为 v1 后端工程子任务。

---

## 数据规格（已与用户确认）

### 文件格式
- ERP 导出的 .xls 实为 HTML 表格
- 25 列固定结构，列名稳定
- 按季度分文件（如 `purchases_2024Q3.xls` / `sales_2024Q3.xls`）

### 列映射（保留 / 忽略）

| 原列 | 处理 | 备注 |
|---|---|---|
| 单号 | ✅ `document_no` | |
| 查看 / 联系方法 / 地址 / 邮编 / 城市 | ❌ 忽略 / dedupe 进主档 | 联系方式 dedupe 到 customers/suppliers 主档 |
| ID号 | ✅ `supplier_id` / `customer_id` | 统一转 string |
| 名称 | ✅ `supplier_name` / `customer_name` | 客户类型识别基于此 |
| 仓库 | ✅ `warehouse` 常量 | 当前都是"店面" |
| 日期 | ✅ `event_at` | `2026/4/27` 格式，无时间，兼容补零/不补零 |
| 型号 | ✅ `product_model` | float → string 去 `.0` |
| 条形码 | ✅ `product_barcode` | float → string 去 `.0`，13 位精度 OK |
| 等级 | ✅ `manual_grade` (1-10, 0=停用) | 仅展示和验证，不进算法 |
| 产品种类 | ✅ `erp_category_raw` + 解析 `erp_category_code` | 形式 `FL017-11 - 塑料大盒子...` |
| 品名 / 本地品名 | ✅ `product_name` / `product_name_local` | |
| 颜色 / 差数 / 备注 / 单据备注 / 状态 | ❌ 忽略 | 噪声列 |
| 数量 | ✅ `qty` | |
| 单价 | ✅ `unit_price` | |
| 折扣 | ✅ `discount_pct` | |
| 金额(€) | ❌ 不存 | 派生 = qty × unit_price × (1-discount/100) |

### 客户/供应商主档**不单独导**
- 主档信息内嵌在每条交易里，import 时 dedupe 出 customers/suppliers 表
- 不需要 ERP 单独导出主档 CSV
- 老外客人的税号/付款/托运是**老外客人模块**自己采集

---

## Schema 变更

### 新表

```sql
-- 客户主档（dedupe 自交易行）
CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    customer_name TEXT NOT NULL,
    customer_type TEXT NOT NULL,  -- 'chinese' / 'foreign' / 'mixed' / 'unknown'
    phone TEXT,
    address TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    notes TEXT
);

-- 供应商主档（dedupe 自交易行）
CREATE TABLE suppliers (
    supplier_id TEXT PRIMARY KEY,
    supplier_name TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT
);

-- 进销存事件（采购 + 销售统一一张表）
CREATE TABLE inventory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_at TEXT NOT NULL,           -- 日期 YYYY-MM-DD
    event_type TEXT NOT NULL,         -- 'purchase' / 'sale'
    product_barcode TEXT NOT NULL,
    qty INTEGER NOT NULL,             -- 总是正数，方向看 event_type
    unit_price REAL,
    discount_pct REAL,
    document_no TEXT,
    shipping_doc TEXT,                -- 物流单（采购特有）
    customer_id TEXT,                 -- sale 时填，关联 customers
    supplier_id TEXT,                 -- purchase 时填，关联 suppliers
    warehouse TEXT,
    erp_category_raw TEXT,
    erp_category_code TEXT,
    manual_grade INTEGER,             -- 1-10 / 0=停用
    imported_at TEXT NOT NULL,        -- 导入时间，调试用
    UNIQUE(event_type, document_no, shipping_doc, product_barcode, event_at, qty, unit_price)
);

CREATE INDEX idx_events_barcode_at ON inventory_events(product_barcode, event_at);
CREATE INDEX idx_events_customer ON inventory_events(customer_id);
CREATE INDEX idx_events_type_at ON inventory_events(event_type, event_at);

-- 老外客人月度记录（独立模块）
CREATE TABLE foreign_customer_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,        -- 关联 customers
    record_month TEXT NOT NULL,       -- 'YYYY-MM'
    amount_due REAL,                  -- 欠款金额
    tax_number TEXT,
    payment_date TEXT,                -- 付款日期
    shipping_date TEXT,               -- 托运日期
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(customer_id, record_month)
);

-- 导入配置（列映射向导）
CREATE TABLE import_profiles (
    profile_name TEXT PRIMARY KEY,    -- 'purchase' / 'sales'
    column_mapping_json TEXT NOT NULL,
    last_used_at TEXT
);
```

### stockpile 表加字段

```sql
ALTER TABLE stockpile ADD COLUMN manual_category TEXT;
-- 值：null / '季节性' / '网红昙花' / '应需采购' / '消耗品' / '长期产品' / '阶段性多峰' / '滞销'
ALTER TABLE stockpile ADD COLUMN auto_category TEXT;
-- 值：null / 'stable' / 'declining' / 'new' / 'seasonal' / 'unclassified'
ALTER TABLE stockpile ADD COLUMN auto_category_computed_at TEXT;
ALTER TABLE stockpile ADD COLUMN product_name_zh TEXT;
ALTER TABLE stockpile ADD COLUMN product_name_local TEXT;
ALTER TABLE stockpile ADD COLUMN erp_category_raw TEXT;
ALTER TABLE stockpile ADD COLUMN erp_category_code TEXT;
ALTER TABLE stockpile ADD COLUMN manual_grade INTEGER;
```

---

## 算法层

### 客户类型识别

```python
def classify_customer(name: str) -> str:
    has_greek = any(0x0370 <= ord(c) <= 0x03FF for c in name)
    has_chinese = any(0x4E00 <= ord(c) <= 0x9FFF for c in name)
    if has_greek and not has_chinese: return 'foreign'
    if has_chinese and not has_greek: return 'chinese'
    if has_greek and has_chinese:     return 'mixed'
    return 'unknown'
```

### 自动 4 类分类

按**总销售时间序列**判（v1 不拆客户端进算法）：

| 类别 | 规则 |
|---|---|
| **新品观察** | 首次销售距今 < 4 周 |
| **季节性**（默认开） | 周销量序列长度 ≥ 52 周 + 滞后 52 周 ACF > 0.5 + 在 ≥ 2 个完整年度内重复峰季 |
| **稳定** | 寿命 ≥ 26 周 + 销售周占比 ≥ 50% + 最近 12 周斜率 ∈ [-10%, +10%] |
| **衰退** | 最近 4 周斜率 < 0 持续 + 上一季度销量比再上一季度跌 ≥ 30% |
| **未分类** | 不满足以上任何一条 |

判定优先级：新品 > 季节性 > 衰退 > 稳定 > 未分类（防冲突）。

`manual_category` 不为 null 时，**人工标签覆盖自动**。

### 派生指标（dashboard 展示）

每个 SKU 算 4 个销售基础数 + 3 个采购派生数 + 客户端拆分：

```
销售面（4）：
  total_qty / total_revenue / unique_customers / lifespan_days
  trend_slope_12w (最近 12 周线性回归斜率，归一化为周变化%)

采购面（3，2026-05-05 新增）：
  stock_balance     - 库存推算 = sum(purchase qty) - sum(sale qty)，与 stockpile 当前库存对照
  avg_margin_pct    - 毛利率 = (售均价 - 进均价) / 售均价 × 100
  purchase_freq     - 最近 365 天采购次数 + 上次采购距今天数

中国端：cn_qty / cn_customers / cn_max_single / cn_last_at
老外端：fo_qty / fo_customers / fo_avg_freq_per_month / fo_last_at
```

不落表，dashboard 查询时即时计算（5 万 SKU 单次 SQL，加合适索引应能 < 5s）。

---

## UI 层

### 货号详情页扩展

在现有「货号查询」页面下加新 panel：

1. **基础指标**（销售 4 个数 + 寿命）
2. **采购信息小栏**（库存推算 / 毛利率 / 采购频率 + 上次采购距今）
3. **客户端横向双栏**：🇨🇳 中国端 / 🇬🇷 老外端
4. **分类标签**：自动标签 + manual_category 下拉（8 选项）
5. **等级对照**：ERP 等级 vs 销量百分位
6. **销售/进价时间线**（同一 Canvas chart，按周聚合：销售点状图 + 进价折线，对照看价格波动 vs 销量波动）

### 销售分析列表页（新顶级 tab "📊 销售分析"）

- 列表所有 SKU + 关键指标 + 自动分类标签
- 筛选：按 auto_category / manual_category / 客户端表现
- 排序：销量 / 寿命 / 趋势 / 等级
- 列表页加"等级 vs 数据不一致告警"列：等级 ≥ 8 但销量在末位 30% / 等级 ≤ 3 但销量在头部 30%

### 老外客人模块（新顶级 tab "🌍 老外客人"）

- 月度记录列表：每月 / 每客户一条
- 字段：欠款 / 税号 / 付款日期 / 托运日期 / 备注
- 关联 customers 表（自动从交易里 dedupe 出来的客户）
- 月度汇总 PDF 导出

---

## PR 拆分

### 阶段 4：数据基础（~3 周）

**PR 4.1 — Schema + 单元测试**（2-3 天）
- alembic migration 加 4 张新表 + stockpile 加字段
- 客户类型识别函数 + 测试
- ERP 类别解析函数（拆 `code - description`）+ 测试

**PR 4.2 — Import infra（HTML xls + 列映射向导）**（4-5 天）
- HTML xls 解析（pandas.read_html）
- 列映射向导（一次性配置，存 import_profiles）
- 4 个 import endpoint（purchase / sales 共用基础 importer）
- importer 自动 dedupe customers / suppliers
- 自动 INSERT 新 SKU 进 stockpile
- 单元测试覆盖：列映射 / dedupe / 重复 import 不重复落库

**PR 4.3 — 4 年历史数据导入**（用户操作 + 验证 1-2 天）
- 用户从 ERP 导出所有季度文件
- 通过向导配好映射 + 批量 import
- 验证：行数对得上、客户/供应商数对得上、等级分布合理

**PR 4.4 — 老外客人模块**（5 天）
- 后端 service + routes（CRUD 月度记录）
- 前端 tab + 列表 + 编辑 + PDF 导出
- 单元测试

### 阶段 5：分析与展示（~3.5 周）

**PR 5.1 — 后端指标计算**（5-6 天）
- analytics_service.py：销售 4 个基础指标 + **采购 3 个派生指标**（库存推算 / 毛利率 / 采购频率） + 客户端拆分
- ACF 季节性识别（v1 用 numpy 实现，不引入 statsmodels）
- 4 类自动分类 service
- 后台定时任务：每天凌晨重算所有 SKU 的 auto_category
- 单元测试：边界值 / 季节性合成数据 / 衰退合成数据 / 库存推算正负边界 / 毛利率边界

**PR 5.2 — Dashboard UI**（6-7 天）
- 货号详情页扩展（销售指标 + **采购信息栏** + 双栏 + 分类下拉 + 等级对照）
- 销售分析列表页（筛选 + 排序 + 不一致告警）
- **销售/进价时间线 Canvas 自绘**（同一 chart 双 series：销售点状 + 进价折线，对照价格波动 vs 销量波动），不引入 ECharts，**保持 v1 不引入 npm 包的承诺**

**PR 5.3 — 收尾 + 优化**（3-5 天）
- 性能优化（5 万 SKU 列表页响应 < 3s）
- xls 下载慢的优化（用 dev tools 抓 ERP web 端 endpoint，做"直连抓取"工具）
- e2e smoke 加 3 个 case：销售分析页加载 / 老外客人页加载 / 货号详情新 panel
- 端到端手测

---

## 不做的（明确划界）

- ❌ 7 类决策树自动分类（季节/网红/应需/消耗品/长期/阶段性多峰）—— 留 v2
- ❌ Prophet / LSTM 任何 ML 预测模型 —— 留 v2 起步
- ❌ 反馈循环 UI（"分类对/不对"按钮）—— v1 只采集 manual_category 数据，UI 留 v2
- ❌ ECharts / Tailwind / Vite —— 阶段 5 v1 不引入第一个 npm 包
- ❌ 客户端拆分进算法层 —— v1.1 议题
- ❌ ERP 主档单独导入 —— 主档全靠交易行 dedupe
- ❌ **供应商分析页**（按供应商切片货周转排名 / 交期 / 单价变化）—— 留 v2，等真发现"我经常按供应商切片"再做
- ❌ **采购单查询页**（按物流单/单号回查）—— 留 v2，等真发现需要这个查询入口再做

---

## 升级触发信号（v2 启动时机）

| 信号 | 升级动作 |
|---|---|
| 用户每周打开 dashboard 看相同指标做相同判断 | 把判断写成自动规则 |
| 用户说"我希望系统判网红/消耗品" | 上 7 类决策树 |
| 用户说"下个月该备多少" | 上 Prophet |
| 用户经常需要按供应商切片对比 | 上供应商分析页 |
| 用户经常想按物流单/单号回查 | 上采购单查询页 |
| manual_category 标签累积 ≥ 200 个 | 用反馈训练阈值 |
| 列表页 SQL 超过 5s | 落表 + 后台异步算 |
| 用户开始要 ECharts 才能讲清楚的图 | 引入 Vite + ECharts |

跑 3-6 个月没出现这些信号 = 中和版已经够用，不必升级。

---

## 测试策略

- 单元测试：每个 PR 自带（保持当前 332 → 400+ 测试增量）
- e2e：阶段 5 收尾时加 3 个 case
- 真实数据验证：阶段 4 历史 import 后，用户对照几个标杆 SKU 看数据/分类合不合理
- 不做：性能 benchmark（除非超 5s 阈值）/ ML 模型评估（v1 没 ML）

---

## 时间预估

- 阶段 4：~3 周（含历史数据导入和老外客人模块）
- 阶段 5：~3.5 周（含 Tier 1 采购派生指标 + 进价趋势线）
- **共 ~6.5 周（按单 session 工作量算，包含手测和迭代时间）**

按 PR 拆，每个 PR 独立可合可回滚，不必一口气做完。
