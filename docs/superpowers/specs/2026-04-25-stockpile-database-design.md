# Stockpile 本地数据库化设计

**日期：** 2026-04-25
**状态：** 待审核

## 目标

将标签处理功能中的 stockpile（系统导出库存文件）从每次手动上传 CSV 改为本地持久化数据库，实现：
1. 处理过程中的修改自动累积到数据库
2. 过渡期内月度比对校验
3. 稳定后彻底取消系统导出上传步骤

## 方案选型

**选择：SQLite（Python 内置 sqlite3）**

- 零额外依赖，单文件 `stockpile.db`，与现有文件系统架构契合
- 万级数据量下查询毫秒级，SQL 支持比对/统计/检索灵活
- 放弃：增强 JSON（无查询能力）、SQLAlchemy（过度设计）

## 架构

```
系统导出文件 ──→ [初始化] ──→ stockpile.db
                                   ↑
                                   │ 自动写入
标签处理(Phase1→2→3) ──────────────┘
    条码纠错 / 新品入库 / 库位变更
                                   │
系统导出文件 ──→ [月度比对] ──→ stockpile.db ──→ 差异报告
```

新增模块 `stockpile_db.py` 封装所有 SQLite 操作，现有处理管线最小改动。

## 数据库表设计

### stockpile（主库存表）

```sql
CREATE TABLE stockpile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_barcode TEXT NOT NULL UNIQUE,    -- 条码
    product_model TEXT NOT NULL,             -- 型号
    stockpile_location TEXT NOT NULL,        -- 库位
    extra TEXT DEFAULT '{}',                 -- 系统导出其他字段(JSON)
    source TEXT DEFAULT 'system_export',     -- 来源
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
```

- `product_barcode` 设 UNIQUE 约束，保证条码不重复
- `extra` JSON 列弹性容纳系统导出的未知字段
- `source` 取值：`system_export` / `scan_new` / `user_correction`

### stockpile_changes（变更日志）

```sql
CREATE TABLE stockpile_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_barcode TEXT NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    change_type TEXT,     -- insert / update / correct
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
```

每次对 stockpile 的修改自动记录到此表，用于审计追溯和比对辅助。

## 功能阶段

### 阶段 1：数据初始化（一次性）

- Web UI 提供上传入口，接收系统导出的 Excel/CSV 文件
- 自动识别列名：`product_barcode`、`product_model`、`stockpile_location` 映射到对应列，其余列存入 `extra` JSON
- 批量 INSERT，遇重复条码跳过或更新
- 初始化完成提示数量

### 阶段 2：处理时自动积累

- `update_location_phase2.py` 不再读取 stockpile CSV 文件，改为调用 `stockpile_db` 查询条码
- 新品条码（扫描发现但不在 stockpile 中的）：处理确认后自动 INSERT，source 标记 `scan_new`
- 条码纠错：`barcode_service.py` 中用户修正条码后自动 UPDATE 数据库并记录变更日志
- 库位变更：库位变化后自动 UPDATE

### 阶段 3：月度比对校验

- 提供"上传系统导出文件进行比对"入口
- 逐条比对：条码是否存在、型号是否一致、库位是否一致
- 生成差异报告，分类：本地有/导出无、导出有/本地无、字段不一致
- 用户可选择"接受系统导出"或有选择地同步

### 阶段 4：取消比对（稳定后目标）

- 连续数月差异为 0 后，可关闭比对功能
- 本地 `stockpile.db` 成为唯一数据源
- 系统导出上传步骤彻底省去

## 实现计划

### 新增文件

| 文件 | 职责 |
|------|------|
| `stockpile_db.py` | SQLite 初始化、CRUD、比对全封装 |
| `routes_stockpile.py` | 初始化上传、月度比对、差异查看路由 |

### 现有文件改动

| 文件 | 改动内容 |
|------|----------|
| `update_location_phase2.py` | `find_latest_stockpile_file()` 替换为 `stockpile_db` 查询 |
| `barcode_service.py` | 条码纠错后调用 `stockpile_db.update_field()` |
| `task_service.py` | 新品条码解析后调用 `stockpile_db.insert_new()` |
| `storage_service.py` | 新增 `save_init_file()` 处理初始化上传 |
| `routes.py` | 注册 `routes_stockpile` 蓝图 |
| `templates/index.html` | 新增初始化和比对 UI 区域 |
| `templates/admin.html` | 控制台端月度比对入口 |
| `.gitignore` | 添加 `stockpile.db` |

### 核心 API（stockpile_db.py）

```
init_db()                        -- 建表（首次自动调用）
import_export(filepath)          -- 初始化：解析导出文件，批量入库
query_by_barcode(code) -> dict   -- 按条码查型号+库位+extra
query_all_barcodes() -> set      -- 获取全部条码集合
insert_new(bar, model, loc, extra, source)  -- 新品入库（带变更日志）
update_field(bar, field, new_val) -- 更新字段（带变更日志）
compare_export(filepath) -> dict  -- 月度比对，返回差异报告
apply_system_updates(diff_items)  -- 接受系统导出覆盖本地
```

## 风险与注意事项

- **编码问题**：系统导出文件可能为 GBK 编码，需自动检测
- **条码格式**：条码可能为纯数字，需统一以字符串处理避免前导零丢失
- **并发**：Flask 单线程开发模式无并发问题；若未来多进程部署需考虑 WAL 模式
- **回退**：保留原有 CSV 读取路径，通过配置开关切换，方便回退
- **备份**：建议定期复制 `stockpile.db` 做离线备份
