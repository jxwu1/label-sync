# 双端处理（label-sync）使用说明

> Internal ERP tool for barcode label processing, inventory matching, sales analytics, and demand forecasting. Built with Flask + SQLAlchemy + pandas. Deployed on Hetzner via Coolify/Docker.

## 1. 项目简介

双端处理是一个基于 Flask 的本地 Web 工具，用来协助完成标签处理相关工作。它提供两个协作端：

- `A 端`：上传文件、开始处理、查看异常、继续处理、下载结果。

处理流程分为三个阶段：

1. `阶段 1`：读取扫描文件，识别条码与库位，检测异常条码长度。
2. `阶段 2`：将扫描结果与系统 `stockpile` 文件匹配，识别新品条码。
3. `阶段 3`：按模板生成导入 CSV，整理输出并归档已处理文件。

## 2. 目录说明

### 顶层结构速览

```
双端处理/
├─ server.py / config.py / routes.py / state.py / schemas.py  ← 入口与运行时基础
├─ routes_*.py                              ← HTTP 蓝图（按业务域命名）
├─ *_service.py                             ← 业务服务层
├─ *_repository.py                          ← 旧式仓库层（input/output/transfer）
├─ models.py / stockpile_db.py              ← ORM + 库存 DB 访问
├─ inventory_importer.py / xls_html_parser.py / customer_classifier.py / erp_category_parser.py
│                                            ← 阶段 4 进销存导入相关
├─ route_helpers.py / file_io.py / location_parser.py / path_safety.py / response_builder.py
│                                            ← 通用工具
├─ phase_scripts/                           ← 标签处理三阶段脚本（subprocess 调用）
├─ alembic/                                 ← schema 迁移
├─ static/ + templates/                     ← 前端（Vanilla JS + Alpine）
├─ tests/                                   ← pytest 单元 + 路由集成
├─ e2e/                                     ← Playwright 浏览器烟雾测试（opt-in）
├─ docs/                                    ← 设计 spec / 阶段 plan / 决策日志
│   └─ zh/                                   ← 中文产品文档与历史更新日志
├─ _scratch/                                ← 本地一次性脚本（gitignored）
├─ input/ / output/ / transfer/ / archive/   ← 运行时数据目录（gitignored）
└─ requirements.txt + requirements-dev.txt + pyproject.toml + alembic.ini
```

> **导航提示**：找路由看 `routes_<域>.py`；找业务逻辑看 `<域>_service.py`；找 schema 看 `models.py`；找历史决策看 `docs/superpowers/plans/2026-04-28-roadmap.md`。

### 详细模块清单

- `server.py`：Flask 服务入口。
- `config.py`：运行配置与目录配置。
- `routes.py`：蓝图注册入口。
- `routes_pages_tasks.py`：页面、任务处理、状态、条码修正相关路由。
- `routes_query.py`：查询、下载、统计相关路由。
- `routes_transfer.py`：文件互传相关路由。
- `routes_collab.py`：文本互传与重复检查相关路由。
- `route_helpers.py`：路由层通用响应辅助方法。
- `state.py`：全局路径、锁、任务状态、消息状态。
- `schemas.py`：内部 dataclass 与统一服务结果类型。
- `storage_service.py`：上传、打包、输出目录、互传文件管理。
- `output_repository.py`：`output/` 目录访问。
- `transfer_repository.py`：`transfer/` 目录访问。
- `task_service.py`：三阶段任务执行与后台调度。
- `barcode_service.py`：异常条码修正与删除。
- `query_service.py`：条码列表、型号列表、文件列表、月度统计查询。
- `message_service.py`：文本互传消息管理。
- `duplicate_service.py`：重复值检查上传处理。
- `phase_scripts/update_location_phase1.py`：阶段 1，扫描数据解析与异常条码检测。
- `phase_scripts/update_location_phase2.py`：阶段 2，系统匹配与新品条码识别。
- `phase_scripts/update_location.py`：阶段 3，输出结果生成与归档。
- `check_duplicates.py`：重复值检查工具，检查上传文件第一列是否重复。
- `templates/`：前端页面模板。
- `input/`：待处理输入目录。
- `output/`：处理结果目录。
- `transfer/`：双端互传文件目录。
- `archive/`：已处理原始文件归档目录。

## 2.1 当前模块边界

建议按下面的原则继续扩展：

- 新增接口：优先放到 `routes.py`
- 更具体地说：先决定属于哪个蓝图，再放到对应 `routes_*.py`
- 新增处理流程或任务编排：优先放到 `task_service.py`
- 新增文件读写、归档、导出：优先放到 `storage_service.py`
- 新增查询类接口：优先放到 `query_service.py`
- 新增消息、通知、协作功能：优先放到 `message_service.py`
- 新增条码人工处理规则：优先放到 `barcode_service.py`
- 新增独立校验器或分析器：优先单独建一个 `*_service.py`

当前内部约定：

- 共享运行状态统一放在 `state.py` 的状态对象中，不直接扩散裸字典
- 跨模块的结构化数据优先定义在 `schemas.py`
- 对外接口仍然返回 JSON，但内部尽量先用 dataclass，再在边界层转成 dict
- 文件系统访问优先收敛到 `*_repository.py`，service 层尽量不直接遍历目录
- 运行参数、路径、编码策略优先收敛到 `config.py`
- Python 标识符统一使用英文 `snake_case`，用户可见文案保留中文

## 3. 运行环境

- Python 3.10 及以上
- 已安装依赖：
  - `flask`
  - `pandas`
  - `openpyxl`

如果当前环境还没安装依赖，可执行：

```powershell
pip install flask pandas openpyxl
```

## 4. 启动方法

在 `双端处理` 目录下执行：

```powershell
python server.py
```

启动后终端会输出访问地址，例如：

```text
服务已启动，A机浏览器访问：http://127.0.0.1:5000
```

常用页面：

- `http://127.0.0.1:5000/`：A 端主页面

## 5. 文件准备要求

放入或上传以下文件：

- 扫描文件：`.xlsx`
- 系统文件：文件名中包含 `stockpile` 的 `.csv`
- 模板文件：文件名中包含 `模板` 的 `.csv`

说明：

- 可以上传多个扫描文件，系统会合并处理。
- 扫描文件默认取第一列进行解析。
- 模板文件只保留表头，最终结果会按模板列结构输出。

## 6. A 端使用流程

1. 打开主页面。
2. 上传扫描文件、系统文件、模板文件。
3. 点击“开始处理”。
4. 如果出现异常条码：
   - 可直接修正条码。
   - 可删除错误条码。
   - 处理完后点击“继续处理”。
5. 如果发现新品条码：
   - 先人工确认是否允许继续。
   - 确认后点击“继续处理”。
6. 处理完成后下载结果压缩包。

## 7. 输出结果说明

处理完成后，`output/` 下会生成一个以员工名和时间戳命名的目录，例如：

```text
ISLAM价格标20260408112637
```

目录内通常包含：

- 处理后的模板 CSV
- 原始扫描文件的整理版 Excel

同时系统会自动生成同名 `.zip` 压缩包，供页面下载。

## 8. 自动归档规则

处理完成后：

- 扫描文件会被移动到 `archive/`
- 系统 `stockpile` 文件会被移动到 `archive/`
- 模板文件会保留在 `input/`

这样便于重复使用模板，同时保留处理记录。

## 9. 重复检查功能

主页面提供“重复检查”功能：

- 支持 `.xlsx`、`.xls`、`.csv`
- 默认检查第一列
- 返回重复值、出现次数和对应行号

适合在处理前先排查重复条码或重复型号。

## 10. 互传功能

系统支持双端协作：

- 文件互传：在 `transfer/` 目录共享文件
- 文本互传：在页面右侧发送简短消息

适合 A 端之间快速交换信息。

## 11. 货号历史页

A 端的"📜 货号历史" tab 提供条码查询功能：

- 输入条码或型号查询当前主表中的库位、状态、来源等信息
- 显示所有历史变更记录，按时间倒序排列
- 只读功能，不可编辑

## 12. 编码说明

本目录脚本和页面统一按 `UTF-8` 保存和读取。

注意事项：

- 模板和系统 CSV 会优先按 `UTF-8` 读取，失败时回退到 `GBK`
- 服务与子进程之间的日志输出统一按 `UTF-8` 处理
- 如果 Windows 终端显示中文异常，优先检查终端编码，而不是直接改源码内容

推荐在 PowerShell 中使用 UTF-8：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

## 13. 常见问题

### 1. 页面提示“没有收到文件”

原因通常是没有正确上传文件，或上传时文件列表为空。

### 2. 提示找不到模板文件或 stockpile 文件

请确认文件名中包含以下关键字：

- 模板文件：`模板`
- 系统文件：`stockpile`

### 3. 阶段中断后无法继续

请不要手动删除 `input/` 中以下临时文件：

- `_temp_mapping.json`
- `_temp_results.json`

它们用于阶段间传递中间结果。

### 4. 中文显示乱码

先确认：

- 源码文件是否是 UTF-8
- 终端是否使用 UTF-8 输出
- CSV 文件本身是否来自 GBK 编码源

当前代码已经对 UTF-8 / GBK 做了兼容读取。

## 14. 开发建议

- 修改 Python 文件时统一保存为 `UTF-8`
- 不要把临时结果文件提交到版本库
- 如需增加规则，优先在阶段脚本中补充，而不是把业务逻辑塞进前端
