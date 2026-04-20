# Module Reuse Design — 方案 B

**日期**: 2026-04-20
**分支**: refactor/module-reuse

## 目标

将 Python 后端模块复用率从 23% 提升到 ~40%，JS 前端从 0% 提升到 ~15%，
同时降低 index.js 单文件行数（1142→~120）。

## Python: 新建 `file_io.py`

层：`lib`（纯工具，无业务语义）

提取以下共享函数：

| 函数 | 来源 | 改动 |
|------|------|------|
| `read_csv(path)` | `update_location.py:19-23`, `update_location_phase2.py:18-22` | 两处相同合并为一 |
| `find_latest_stockpile_file(directory)` | `storage_service.py:48-52`, `update_location_phase2.py:191-195` | 参数化 directory |
| `find_single_file(directory, pattern, description)` | `update_location_phase1.py:24-29` | 参数化 directory |
| `read_input_file(path)` | `check_duplicates.py:8-17` | 统一 xlsx/csv + 编码回退 |
| `update_json_file(path, modifier_fn)` | `barcode_service.py` 内6处读-改-写模式 | 传入 modifier 函数 |

### 调用方改动

- `update_location.py`: `from file_io import read_csv` + `find_latest_stockpile_file(INPUT_DIR)`
- `update_location_phase1.py`: `from file_io import find_single_file` + `find_single_file(str(INPUT_DIR), ...)`
- `update_location_phase2.py`: `from file_io import read_csv, find_latest_stockpile_file`
- `storage_service.py`: `from file_io import find_latest_stockpile_file`
- `check_duplicates.py`: `from file_io import read_input_file`
- `barcode_service.py`: `from file_io import update_json_file` → 6处重复模式简化

### phase1 的 SystemExit 处理

原始 `find_single_file` 在找不到文件时 raise SystemExit(1)。
提取后共享函数返回 `None`，调用方自行决定是否 raise：

```python
file = find_single_file(str(INPUT_DIR), "*模板*.csv", "template csv")
if file is None:
    print("ERROR: missing template csv in input/")
    raise SystemExit(1)
```

## JS: 新建共享 ES Module 文件

### `static/js/shared.js`

```js
export function esc(value) { ... }         // HTML 转义
export function escapeAttr(value) { ... }   // HTML 属性转义
export function jesc(value) { ... }         // JS 字符串转义
export async function copyToClip(text) { ... } // 剪贴板复制（含 fallback）
export function setupDropZone(dropEl, inputEl, onFiles) { ... } // 拖拽上传
export function logClass(text) { ... }      // 日志分类
```

### `static/js/transfer.js`

```js
export async function uploadTransferFiles(files) { ... }
export async function loadTransferFiles() { ... }  // 返回 items 数组
export async function deleteTransferFile(filename) { ... }
```

### `static/js/messaging.js`

```js
export async function sendTextMessage(text, sender) { ... }
export async function loadMessages() { ... }  // 返回 messages 数组
export async function deleteMessage(id) { ... }
```

## JS: 拆分 `index.js`

| 新文件 | 职责 | 导出 |
|--------|------|------|
| `index-dom.js` | DOM 引用 + setBadge/setStatus/term/renderLog/renderFiles/clearLog | 共享 state |
| `index-poll.js` | startPoll + handleStatus + restore | startPoll, handleStatus, restore |
| `index-warnings.js` | 条码/库位/phase2警告渲染 + parseP2WFromLog | renderReview |
| `index-actions.js` | submitBc/delBc/submitLoc/resolveEx/submitNewBc/delNewBc/copyModels 等 | 各种 action |
| `index-dup.js` | 多库位选择UI（p2DupSel/dedupWithSources/badgeFor 等） | renderDupCard, 相关函数 |
| `index.js` | 初始化 + 编排 | 入口 |

### 依赖关系

```
index.js (入口)
  ├─ index-dom.js (DOM state)
  ├─ index-poll.js (轮询)
  │    └─ index-dom.js, index-warnings.js
  ├─ index-warnings.js (警告渲染)
  │    └─ index-dom.js, index-dup.js, shared.js
  ├─ index-actions.js (用户操作)
  │    └─ index-dom.js, shared.js
  ├─ index-dup.js (多库位UI)
  │    └─ shared.js
  ├─ transfer.js
  ├─ messaging.js
  └─ shared.js
```

## HTML 模板改动

`templates/index.html`:
```html
<script type="module" src="{{ url_for('static', filename='js/index.js') }}"></script>
<!-- 删除 purchase.js 的单独 script 标签，改为 index.js 内部 import 或保留 -->
```

`templates/admin.html`:
```html
<script type="module" src="{{ url_for('static', filename='js/admin.js') }}"></script>
```

注意：改为 `type="module"` 后，所有 `window.xxx = function` 挂载仍然可用
（因为 onclick="xxx()" 需要 window 上的全局函数）。

## 不做的事情

- 不创建 `phase_config.py`
- 不重构 `purchase.js` 内部 IIFE 结构
- 不改变测试结构

## 验证

- 现有 63 个测试全部通过
- 新建 file_io.py 的单元测试
- 手动验证前端页面功能正常