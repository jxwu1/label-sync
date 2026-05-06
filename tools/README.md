# tools/

运维 / 一次性 / 周期性任务的 CLI 工具。和业务代码（routes/services）分开，避免污染主代码库。

## inventory_admin.py

进销存批量导入 + 验证。

### 1. 批量导入 4 年历史数据（PR 4.3 主用例）

把所有 ERP 导出的 .xls 放在一个文件夹里，文件名带 `purchase` / `采购` 或 `sale` / `销售` 关键词，例如：

```
exports/
├─ purchases_2022Q1.xls
├─ purchases_2022Q2.xls
├─ ...
├─ sales_2022Q1.xls
├─ sales_2022Q2.xls
└─ ...
```

然后跑：

```sh
python tools/inventory_admin.py import-batch exports/
```

输出每个文件的 import 结果 + 末尾汇总。**幂等**：再跑一遍同一目录不会重复落库（UNIQUE 约束去重）。

只导某一类型：

```sh
python tools/inventory_admin.py import-batch exports/ --type purchase
python tools/inventory_admin.py import-batch exports/ --type sale
```

文件名推断不出类型时会跳过并打印警告，**不会**报错或污染数据。

### 2. 验证导入结果

```sh
python tools/inventory_admin.py stats     # 聚合计数 + 客户类型分布 + 日期范围
python tools/inventory_admin.py verify    # 异常检查（负 qty / 零单价 / 无 partner 等）
```

### 3. 周期性增量导入

每月 ERP 出新数据时，把当月导出文件丢进同一目录再跑一次 `import-batch`。已导入的旧文件被 UNIQUE 约束自动跳过，新行落库。

## 注意

- 这些工具直接操作生产 stockpile.db，不走 HTTP；速度快但**没有 web UI 的 import 进度反馈**
- 大批量导入（百万行级）建议分批：每次 50-100 个文件
- 出错时会跳过该文件继续下一个，但事件仍可能部分落库（commit 在文件粒度），失败的文件查日志后单独重试即可
