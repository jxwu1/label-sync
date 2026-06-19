# dev.ps1 零依赖本地进程监督器 设计

**状态：** 已批准（2026-06-19，终审 APPROVE）。审查处置：①pg_isready 替代 TCP 就绪探测；②ReadLineAsync EOF/drain 契约 + 就绪探测并入监督循环 + npm.cmd；③Vite 显式绑定 --host 127.0.0.1 + Ctrl+C 130 脚本显式设；④语法检查用 Parser API 不 dot-source；⑤端口复查只查本脚本**监督过**的端口（:5000 恒查 / :5173 仅 -Frontend，避免误伤独立 Vite）+ 统一 `$desiredExitCode` 单源 + api 只用 `python -u`（删 PYTHONUNBUFFERED 歧义）。

## 目标

把 `dev.ps1` 升级成**零依赖**轻量本地进程监督器：Flask（:5000）+ Vite（:5173）在**同一 PowerShell 终端**运行，输出加 `[api]`/`[web]` 前缀逐行实时打印，Ctrl+C 关两进程树，任一意外退出报码并清理另一个。**不引入** Nx/Turbo/concurrently/dev container（仓库根禁 Node 工程；Windows+PowerShell 已是既有开发入口；生产日志由 Docker/Coolify 管，本次只解决本地体验）。**Windows-only**（已确认）——进程树清理走 `taskkill /T`。

## 范围

- Modify: `dev.ps1`（唯一生产文件）。
- 前半（PG + env + alembic）**命令与顺序保持不变**，仅补退出码检查 + 就绪探测 + 文案。后半（双进程监督）重写。
- `-Frontend` 开关语义不变：不带 → 仅监督后端（同现状）；带 → 监督 api + web。
- 不引入 Pester（本期）。

## §1 前半：PG 就绪 + 退出码闸（命令/顺序不变）

执行顺序不变，但加正确性：

1. `docker compose -f docker-compose.dev.yml up -d` → **非零打警告但不退出**（**实测修订**：`dev-pg` 是持久容器，已存在时 `up -d` 因名字冲突返回非零，但 PG 实际在跑；硬退会让脚本每次都假失败。**`pg_isready` 才是权威就绪闸**——它没过才算 PG 不可用）。
2. **PG 就绪探测**（`pg_isready` 重试，最多 30s，权威闸）：
   ```powershell
   docker exec label-sync-dev-pg pg_isready -U dev -d label_sync
   ```
   **实测修订**：用 `docker exec <container_name>`（容器名 `label-sync-dev-pg` 在 compose 里 pinned）而非 `docker compose exec <service>`——后者在容器名冲突/孤儿态（容器属另一 compose project，见 [[project_local_pg_derived_cols_empty]]）下报 "service dev-pg is not running" 恒失败。循环重试；**此处非零是预期重试状态**（不触发退出）；30s 仍未 ready → 报错退出。ready 后打 `[dev] PostgreSQL ready · :5433`。
   > 用 `pg_isready` 而非 TCP :5433 探测：Docker 端口代理可能先于数据库接受查询就绪，TCP 可连接 ≠ PG 能接受查询 → 紧接的 alembic 会连接失败。
3. 设 `$env:DATABASE_URL` / `$env:LABEL_SYNC_DEBUG`（不变）。
4. `python -m alembic upgrade head` → **查 `$LASTEXITCODE`，非零报错退出**；成功才打 `[dev] Alembic upgrade complete`。

> **退出码处理（实测后定稿）**：`alembic` 非零→立即退出（无就绪代理）；`docker compose up` 非零→**仅警告**（容器已存在冲突常态，PG 仍可用，由 pg_isready 裁决）；`pg_isready` 非零→重试（30s 超时才退）。`$PSNativeCommandUseErrorActionPreference=$false` 时 `$ErrorActionPreference='Stop'` 不一定拦原生命令非零，故均显式查 `$LASTEXITCODE`。`pg_isready` 作权威就绪闸，已堵住「docker 失败却打 ready 成功」的红队隐患（pg_isready 没过绝不打 ready）。

## §2 进程监督：修订后的 A（System.Diagnostics.Process + 主循环 ReadLineAsync）

每个被监督进程用 `System.Diagnostics.Process`：`UseShellExecute=$false`、`RedirectStandardOutput=$true`、`RedirectStandardError=$true`、`CreateNoWindow=$true`，工作目录 / 环境按需设。

- **api**：`python -u server.py`（`-u` 防管道缓冲；**只用 `-u`，不再叠加 `PYTHONUNBUFFERED`**，消除实现歧义），工作目录＝仓库根。
- **web**（仅 `-Frontend`）：可执行 = **`cmd.exe`**，参数 `/c npm run dev -- --host 127.0.0.1 --strictPort --clearScreen false`，工作目录＝`frontend/`，环境加 `FORCE_COLOR=1`。（**实测修订**：原定 `npm.cmd` 经 .NET Process 直跑会让 npm 的 `%~dp0` 解析错乱 → 去 `frontend\node_modules\npm\` 找 npm 自身 → MODULE_NOT_FOUND；改 `cmd.exe /c npm` 由 cmd 从 PATH 正确解析。cmd.exe 为被监督进程，node/vite 是其子，taskkill /T 杀整树。）
  - `--host 127.0.0.1`：让 TCP 探测、打印 URL、实际监听地址三者一致。
  - `--strictPort`：避免端口检查后竞态自动跳 5174。
  - `--clearScreen false`：Vite 8.0.16 支持；**`--color` 不支持，不加**。

**输出读取（核心，按实测纠正）：**

- ❌ **不**注册 PowerShell scriptblock 到 `OutputDataReceived`/`ErrorDataReceived`——输出到达即「There is no Runspace available to run scripts in this thread」崩溃。
- ✅ **主 runspace 单循环轮询 `StandardOutput.ReadLineAsync()` / `StandardError.ReadLineAsync()`**（或 Add-Type C# 回调；本期用 ReadLineAsync）。每条完成的行加前缀打印，再对该流续发 ReadLineAsync。
- **EOF 契约**：`ReadLineAsync()` 完成结果为 `$null` 表示该流 EOF → **停止对该流续发读取**（防空转 busy-spin）。
- **每轮排空（实测修订）**：每条流每轮**循环读完当前所有已就绪行**（`while IsCompleted`，非单行），且**本轮有输出就不 sleep、立刻再循环**，仅空闲时 `Start-Sleep 25ms`。否则单行节流会把两进程日志逐行轮流挤出（挤牙膏感）+ 缓冲日志拖慢。
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
  超时未监听（**~30s，Stopwatch 计**）：进程**活着但始终不监听端口** → 设 `$desiredExitCode=1` + 清理 + 退出，避免永久挂起。（进程若已退出则走上面的退出判定，不算就绪超时。）
- **统一退出码 `$desiredExitCode`**：单一真源，三处赋值——Ctrl+C = **130**；子进程意外退出 = **其 `ExitCode`**；启动/就绪失败 = **对应非零码**（docker/alembic 的 `$LASTEXITCODE`、就绪超时 = 1）。`finally` **只负责清理，绝不改写 `$desiredExitCode`**；脚本末尾 `exit $desiredExitCode`。
- **Ctrl+C**：纯 C# `Console.CancelKeyPress` 处理器（`Add-Type`，不经 PS runspace）置 volatile 标志；主循环置顶轮询→设 `$desiredExitCode = 130`→break。Install **幂等** + 保存 delegate + `finally` 调 **`Uninstall()`** 卸载（防同会话多次运行累积处理器）。（实测：`TreatControlCAsInput`+`KeyAvailable` 读键在 Windows Terminal 下检测不到 Ctrl+C 致关不掉，已弃用。）
- **启动纳入 try（实测修订）**：进程启动（`Start-Supervised` + `Add` 进 `$supervised`）放在 `try` 内、`$supervised` 在 `try` 外声明——web 启动/ReadLineAsync 任一步抛错时，已起的 api 仍被 `finally` 清理，不残留 :5000。
- **退出判定（实测修订）**：不凭「所有进程已退」early-break（会丢退出码 + 尾日志）。必须 drain 到 `outEof && errEof` 后，凭 `HasExited && outEof && errEof` 捕获该进程真实 `ExitCode` 再 break。
- **任一意外退出**：先把该子进程 `ExitCode` 赋给 `$desiredExitCode`（**在任何 `taskkill` 之前**，避免被 `$LASTEXITCODE` 覆盖）→ drain 该进程管道 → 打印 `[api|web] exited (code <N>)` → 清理另一棵树。
- **清理函数（幂等）**：对每个存活进程 `taskkill /T /F /PID <pid>`；**进程已退 / 「找不到进程」不当新错误**（吞掉）。**清理后端口复查只查本脚本监督过的端口**（遍历 `$supervised` 取各 entry 的 `port`）：**:5000 恒查；:5173 仅 `-Frontend` 时查**（被监督过才查）。仍监听则告警 `[dev] ⚠ 端口 :<port> 仍被占用，可能有孤儿进程`。
  > **为何按监督端口而非固定 :5000/:5173**：仅后端模式下用户可能**独立**跑着自己的 Vite（:5173）；若无条件复查 :5173，停 API 后会把那个**正常**进程误报成孤儿。只查 `$supervised` 里的端口即可避免。
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
10. **独立 Vite 占 :5173 + 仅后端模式不误伤**：另起一个独立 Vite（或任意进程）监听 :5173 → `./dev.ps1`（**无** `-Frontend`）起停 → 全程**不杀**该 :5173 进程、清理后**不**对 :5173 告警（只复查 :5000）；该独立进程仍存活。

## 不做（YAGNI）

不引 Pester / 不引任何编排器或容器；不做 Windows Job Object 硬隔离（taskkill /T + 端口复查兜底）；不动前半命令/顺序；不改日志内容（仅前置前缀）；不跨平台（Windows-only，Linux/macOS 若将来要支持，进程树清理方案需重做）。
