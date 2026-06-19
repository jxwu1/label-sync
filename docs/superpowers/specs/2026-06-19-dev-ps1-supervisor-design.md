# dev.ps1 零依赖本地进程监督器 设计

**状态：** 已批准（2026-06-19，终审 APPROVE，条件＝写入 4 项终审修订）。审查处置：①pg_isready 替代 TCP 就绪探测；②ReadLineAsync EOF/drain 契约 + 就绪探测并入监督循环 + npm.cmd；③Vite 显式绑定 --host 127.0.0.1 + Ctrl+C 130 脚本显式设；④语法检查用 Parser API 不 dot-source。

## 目标

把 `dev.ps1` 升级成**零依赖**轻量本地进程监督器：Flask（:5000）+ Vite（:5173）在**同一 PowerShell 终端**运行，输出加 `[api]`/`[web]` 前缀逐行实时打印，Ctrl+C 关两进程树，任一意外退出报码并清理另一个。**不引入** Nx/Turbo/concurrently/dev container（仓库根禁 Node 工程；Windows+PowerShell 已是既有开发入口；生产日志由 Docker/Coolify 管，本次只解决本地体验）。**Windows-only**（已确认）——进程树清理走 `taskkill /T`。

## 范围

- Modify: `dev.ps1`（唯一生产文件）。
- 前半（PG + env + alembic）**命令与顺序保持不变**，仅补退出码检查 + 就绪探测 + 文案。后半（双进程监督）重写。
- `-Frontend` 开关语义不变：不带 → 仅监督后端（同现状）；带 → 监督 api + web。
- 不引入 Pester（本期）。

## §1 前半：PG 就绪 + 退出码闸（命令/顺序不变）

执行顺序不变，但加正确性：

1. `docker compose -f docker-compose.dev.yml up -d` → **查 `$LASTEXITCODE`，非零立即报错退出**（启动命令，非探测）。
2. **PG 就绪探测**（`pg_isready` 重试，最多 30s）：
   ```powershell
   docker compose -f docker-compose.dev.yml exec -T dev-pg pg_isready -U dev -d label_sync
   ```
   循环重试；**此处非零是预期重试状态**（不触发立即退出）；30s 仍未 ready → 报错退出。ready 后打 `[dev] PostgreSQL ready · :5433`。
   > 用 `pg_isready` 而非 TCP :5433 探测：Docker 端口代理可能先于数据库接受查询就绪，TCP 可连接 ≠ PG 能接受查询 → 紧接的 alembic 会连接失败。
3. 设 `$env:DATABASE_URL` / `$env:LABEL_SYNC_DEBUG`（不变）。
4. `python -m alembic upgrade head` → **查 `$LASTEXITCODE`，非零报错退出**；成功才打 `[dev] Alembic upgrade complete`。

> **「原生命令非零立即退出」仅限非探测命令**（docker up、alembic）。`pg_isready` 等探测命令的非零是正常重试信号，不得当失败。`$PSNativeCommandUseErrorActionPreference=$false` 时 `$ErrorActionPreference='Stop'` 不一定拦原生命令非零，故必须显式查 `$LASTEXITCODE`。

## §2 进程监督：修订后的 A（System.Diagnostics.Process + 主循环 ReadLineAsync）

每个被监督进程用 `System.Diagnostics.Process`：`UseShellExecute=$false`、`RedirectStandardOutput=$true`、`RedirectStandardError=$true`、`CreateNoWindow=$true`，工作目录 / 环境按需设。

- **api**：`python -u server.py`（`-u` 或 `PYTHONUNBUFFERED=1` 防管道缓冲），工作目录＝仓库根。
- **web**（仅 `-Frontend`）：可执行 = **`npm.cmd`**（Windows，非 `npm`），参数 `run dev -- --host 127.0.0.1 --strictPort --clearScreen false`，工作目录＝`frontend/`，环境加 `FORCE_COLOR=1`。
  - `--host 127.0.0.1`：让 TCP 探测、打印 URL、实际监听地址三者一致。
  - `--strictPort`：避免端口检查后竞态自动跳 5174。
  - `--clearScreen false`：Vite 8.0.16 支持；**`--color` 不支持，不加**。

**输出读取（核心，按实测纠正）：**

- ❌ **不**注册 PowerShell scriptblock 到 `OutputDataReceived`/`ErrorDataReceived`——输出到达即「There is no Runspace available to run scripts in this thread」崩溃。
- ✅ **主 runspace 单循环轮询 `StandardOutput.ReadLineAsync()` / `StandardError.ReadLineAsync()`**（或 Add-Type C# 回调；本期用 ReadLineAsync）。每条完成的行加前缀打印，再对该流续发 ReadLineAsync。
- **EOF 契约**：`ReadLineAsync()` 完成结果为 `$null` 表示该流 EOF → **停止对该流续发读取**（防空转 busy-spin）。
- **drain 契约**：子进程 `HasExited` 后，**先把 stdout+stderr 排空至 EOF 再报告退出**，保证末尾日志不丢。
- **就绪探测并入同一监督循环**：进程一启动**立即开始读管道**；TCP 就绪探测（§3）作为循环内的周期检查，**不得先阻塞等端口再读**——否则重定向管道塞满会阻塞子进程。
- **顺序保证**：只保证**各流（stdout / stderr）内部逐行顺序**；stdout↔stderr 交叉顺序 best-effort。
- **色彩承诺**：只承诺**日志内容完整 + 逐行实时 + 带前缀**；**不承诺 Flask 颜色完全保留**（管道非 TTY，FORCE_COLOR 尽力而为）。

## §3 行为细节

- **启动前端口检查**：检 :5000（恒）、:5173（`-Frontend` 时）。占用 → 打印 `[dev] ⚠ :<port> 占用 (PID <pid>)，请先处理` → **退出，不杀**；被占的原进程必须存活。
- **就绪 = TCP 轮询**（在监督循环内）：轮询 :5000 / :5173 实际监听后才打地址块：
  ```
  [api] Serving http://127.0.0.1:5000
  [web] VITE ready · http://localhost:5173/ui/
  [dev] Ctrl+C stops api + web
  ```
  超时未监听（如 ~30s）→ 报错 + 清理 + 退出。
- **Ctrl+C**：`try { 监督循环 } finally { 清理 }`；退出码 **由脚本显式设为 130**（`exit 130`，不依赖 PowerShell 默认）。
- **任一意外退出**：先**保存该子进程 `ExitCode` 到变量**（避免被随后 `taskkill` 的 `$LASTEXITCODE` 覆盖）→ drain 该进程管道 → 打印 `[api|web] exited (code <N>)` → 清理另一棵树 → 脚本以保存的码退出。
- **清理函数（幂等）**：对每个存活进程 `taskkill /T /F /PID <pid>`；**进程已退 / 「找不到进程」不当新错误**（吞掉）。清理后**复查 :5000/:5173**，仍监听则告警 `[dev] ⚠ 端口 :<port> 仍被占用，可能有孤儿进程`。
  > HIGH 兜底：监督根进程先退时 `taskkill /T` 可能找不到已孤立的后代；**硬保证需 Windows Job Object，本期不做**，以 taskkill /T + 端口复查兜底。
- **仅后端**（无 `-Frontend`）：只监督 api 一个进程，同现状（前台 + Ctrl+C 停 + 退出码传播）。

## §4 验证

进程与 Ctrl+C 行为以**集成手动验收**为主；**纯辅助函数**（端口检查、行前缀格式化、pg_isready 重试封装）可单测，但**本期不引入 Pester**。

**语法解析检查**（CI/本地，**不执行脚本**）：用 Parser API，**严禁 dot-source**（dot-source 会真的跑 docker/迁移/起服务）：
```powershell
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path ./dev.ps1), [ref]$null, [ref]$errors) | Out-Null
if ($errors) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }
```

**手动验收清单：**
1. `./dev.ps1 -Frontend` → api + web 两进程起；`[api]`/`[web]` 双前缀**实时**输出；就绪后打地址块。
2. Ctrl+C → 两进程树全灭；事后 `netstat` 查 :5000/:5173 **无残留**；脚本退出码 130。
3. 手动 kill 其一 → 另一被清理 + 脚本以该子进程退出码退出。
4. 端口预占 → 报 PID + 退出**不杀**；**被占的原进程仍存活**。
5. 无 `-Frontend` → 仅后端，同现状。
6. **Flask 改码触发 reloader 生成新子进程后** Ctrl+C → 新子进程也被清理（taskkill /T 整树）。
7. **Vite HMR 后**清理干净。
8. **连续起停 3 次**，无 :5000/:5173 残留。
9. Parser 语法检查通过。

## 不做（YAGNI）

不引 Pester / 不引任何编排器或容器；不做 Windows Job Object 硬隔离（taskkill /T + 端口复查兜底）；不动前半命令/顺序；不改日志内容（仅前置前缀）；不跨平台（Windows-only，Linux/macOS 若将来要支持，进程树清理方案需重做）。
