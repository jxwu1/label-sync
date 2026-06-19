# dev.ps1 零依赖本地进程监督器 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `dev.ps1` 升级成零依赖 PowerShell 进程监督器：Flask + Vite 同终端、`[api]`/`[web]` 逐行实时前缀、Ctrl+C 关两进程树、任一退出报码并清理另一个。

**Architecture:** 单文件 `dev.ps1`。前半（PG/env/alembic）命令与顺序不变，补 `$LASTEXITCODE` 闸 + `pg_isready` 就绪探测。后半用 `System.Diagnostics.Process`（重定向 stdout/stderr）+ **主 runspace 单循环轮询 `ReadLineAsync()`**（绝不注册 scriptblock 到 OutputDataReceived，会「no Runspace」崩溃）+ EOF/drain 契约 + TCP 就绪探测并入循环 + `try/finally` 清理（`taskkill /T /F`）+ 退出码传播（Ctrl+C=130）。Windows-only。

**Tech Stack:** PowerShell 7（pwsh）、.NET `System.Diagnostics.Process`、`Get-NetTCPConnection`、`taskkill`。

**设计 spec：** `docs/superpowers/specs/2026-06-19-dev-ps1-supervisor-design.md`（终审 APPROVE）。

> **测试现实**：进程编排/Ctrl+C 无法 Pester 单测（本期不引 Pester）。每个任务后跑 **Parser 语法解析检查**（不执行脚本）；最终任务跑 **9 项手动集成验收**并迭代到全过。实现 PowerShell 进程监督需对照真实 `pwsh` 执行迭代（Ctrl+C/finally 语义、ReadLineAsync 边界、taskkill 时序），计划给出可工作的草稿 + 验收闭环。

---

## 文件结构

- Modify: `dev.ps1`（唯一文件）。结构：`param` → `$ErrorActionPreference` → 辅助函数 → 前半（PG/env/alembic）→ 进程监督（含清理 finally）。

---

## Task 1: 辅助函数 + 语法检查基线

**Files:** Modify `dev.ps1`（顶部加辅助函数；暂不改主流程）

- [ ] **Step 1: 在 `param(...)` + `$ErrorActionPreference='Stop'` 之后插入辅助函数**

```powershell
$root = $PSScriptRoot

# 端口被谁占（监听态）→ 返回 PID，否则 $null
function Get-ListeningPid([int]$Port) {
    $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess } else { return $null }
}

# 端口是否已有进程监听（就绪探测用）
function Test-Listening([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

# 幂等清理：杀整进程树；进程已退/找不到不算错
function Stop-Tree([int]$ProcessId) {
    if (-not $ProcessId) { return }
    try { & taskkill /T /F /PID $ProcessId 2>$null | Out-Null } catch { }
}

# 启动一个重定向进程
function Start-Supervised([string]$File, [string[]]$ArgList, [string]$WorkDir, [hashtable]$EnvExtra) {
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $File
    foreach ($a in $ArgList) { [void]$psi.ArgumentList.Add($a) }
    $psi.WorkingDirectory = $WorkDir
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    if ($EnvExtra) { foreach ($k in $EnvExtra.Keys) { $psi.Environment[$k] = [string]$EnvExtra[$k] } }
    $p = [System.Diagnostics.Process]::new()
    $p.StartInfo = $psi
    [void]$p.Start()
    return $p
}
```

- [ ] **Step 2: 语法解析检查（不执行脚本）**

Run（仓库根）:
```powershell
$errs = $null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path ./dev.ps1), [ref]$null, [ref]$errs) | Out-Null; if ($errs) { $errs | % { $_.Message }; exit 1 } else { 'parse OK' }
```
Expected: `parse OK`（退出 0）。

- [ ] **Step 3: 快速验证辅助函数（手动，不起服务）**

Run（仓库根）: `pwsh -NoProfile -Command "& { . { $errs=$null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path ./dev.ps1),[ref]$null,[ref]$errs)|Out-Null }; 'ok' }"`
注：仅确认可解析；**不要** dot-source 整个 dev.ps1（会真起 docker/alembic/server）。函数逻辑在 Task 3 集成验收时连带验证。

- [ ] **Step 4: Commit**

```bash
git add dev.ps1
git commit -m "feat(dev): dev.ps1 监督器辅助函数（端口/清理/启动进程）"
```

---

## Task 2: 前半补退出码闸 + pg_isready 就绪探测

**Files:** Modify `dev.ps1`（替换现有 docker/alembic 段）

- [ ] **Step 1: 替换前半为带闸版本**

把现有的 `docker compose ... up -d` / 设 env / `python -m alembic upgrade head` 段替换为：

```powershell
# 1. 起本地 PostgreSQL 17
docker compose -f docker-compose.dev.yml up -d
if ($LASTEXITCODE -ne 0) { Write-Host "[dev] ✗ docker compose up 失败 (exit $LASTEXITCODE)" -ForegroundColor Red; exit $LASTEXITCODE }

# 2. 等 PG 真正可接受查询（pg_isready 重试最多 30s；此处非零是预期重试，不退出）
$pgReady = $false
for ($i = 0; $i -lt 30; $i++) {
    docker compose -f docker-compose.dev.yml exec -T dev-pg pg_isready -U dev -d label_sync 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $pgReady = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $pgReady) { Write-Host "[dev] ✗ PostgreSQL 30s 内未就绪" -ForegroundColor Red; exit 1 }
Write-Host "[dev] PostgreSQL ready · :5433" -ForegroundColor Green

# 3. 指向本地 PG + 热重载
$env:DATABASE_URL = 'postgresql+psycopg://dev:devpass@localhost:5433/label_sync'
$env:LABEL_SYNC_DEBUG = '1'

# 4. 同步 schema（幂等）
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Host "[dev] ✗ alembic upgrade 失败 (exit $LASTEXITCODE)" -ForegroundColor Red; exit $LASTEXITCODE }
Write-Host "[dev] Alembic upgrade complete" -ForegroundColor Green
```

> `pg_isready` 的非零是重试信号（不立即退出）；只有 docker up、alembic 这类非探测命令非零才立即退出。`dev-pg` 是 `docker-compose.dev.yml` 的服务名（凭据 dev/devpass/label_sync 与 DATABASE_URL 一致）。

- [ ] **Step 2: 语法解析检查**

Run: 同 Task 1 Step 2。Expected: `parse OK`。

- [ ] **Step 3: 手动验证就绪闸（真起 PG，不起 server）**

Run（仓库根，临时把脚本末尾 server 启动注释或此时主流程还没接 server）: 实际跑 `./dev.ps1`（无 -Frontend）观察 `[dev] PostgreSQL ready · :5433` 与 `[dev] Alembic upgrade complete` 按序打印；若 docker 未运行，确认打印 `✗ docker compose up 失败` 并退出非零。
> 注：此时主流程后半（server 监督）尚未实现/仍是旧版；本步只验前半两条 ready 文案 + 退出码闸。Task 3 接后半。

- [ ] **Step 4: Commit**

```bash
git add dev.ps1
git commit -m "feat(dev): dev.ps1 前半补退出码闸 + pg_isready 就绪探测"
```

---

## Task 3: 进程监督主循环 + 信号/清理 + 退出码传播

**Files:** Modify `dev.ps1`（替换现有 `-Frontend` 起前端 + 前台 `python server.py` 段）

- [ ] **Step 1: 替换后半为监督器**

把现有的 `if ($Frontend) { Start-Process ... }` + `python server.py` 段替换为：

```powershell
# 5. 启动并监督进程（api 恒；web 仅 -Frontend）
# 端口预检查：占用则报 PID 退出，不杀
$apiPid = Get-ListeningPid 5000
if ($apiPid) { Write-Host "[dev] ⚠ :5000 占用 (PID $apiPid)，请先处理" -ForegroundColor Yellow; exit 1 }
if ($Frontend) {
    $webPid = Get-ListeningPid 5173
    if ($webPid) { Write-Host "[dev] ⚠ :5173 占用 (PID $webPid)，请先处理" -ForegroundColor Yellow; exit 1 }
}

# 待监督进程表
$supervised = [System.Collections.ArrayList]::new()
$apiProc = Start-Supervised 'python' @('-u', 'server.py') $root $null   # 只用 -u，不叠加 PYTHONUNBUFFERED
[void]$supervised.Add(@{ name = 'api'; proc = $apiProc; port = 5000; url = 'http://127.0.0.1:5000'; ready = $false
    outTask = $apiProc.StandardOutput.ReadLineAsync(); errTask = $apiProc.StandardError.ReadLineAsync(); outEof = $false; errEof = $false })
if ($Frontend) {
    $webProc = Start-Supervised 'npm.cmd' @('run', 'dev', '--', '--host', '127.0.0.1', '--strictPort', '--clearScreen', 'false') (Join-Path $root 'frontend') @{ FORCE_COLOR = '1' }
    [void]$supervised.Add(@{ name = 'web'; proc = $webProc; port = 5173; url = 'http://localhost:5173/ui/'; ready = $false
        outTask = $webProc.StandardOutput.ReadLineAsync(); errTask = $webProc.StandardError.ReadLineAsync(); outEof = $false; errEof = $false })
}

$desiredExitCode = 0   # 单一真源：子进程异常=其 ExitCode；Ctrl+C=130；finally 只清理不改写它
$footerPrinted = $false
try {
    while ($true) {
        $anyAlive = $false
        $exited = $null
        foreach ($s in $supervised) {
            # stdout：完成的行加前缀；$null=EOF 停续发
            if (-not $s.outEof -and $s.outTask.IsCompleted) {
                $line = $s.outTask.Result
                if ($null -eq $line) { $s.outEof = $true }
                else { Write-Host "[$($s.name)] $line"; $s.outTask = $s.proc.StandardOutput.ReadLineAsync() }
            }
            # stderr 同理（各流内部有序；stdout/stderr 交叉 best-effort）
            if (-not $s.errEof -and $s.errTask.IsCompleted) {
                $eline = $s.errTask.Result
                if ($null -eq $eline) { $s.errEof = $true }
                else { Write-Host "[$($s.name)] $eline"; $s.errTask = $s.proc.StandardError.ReadLineAsync() }
            }
            # 就绪探测并入循环（不阻塞）：实际监听后打地址
            if (-not $s.ready -and (Test-Listening $s.port)) {
                $s.ready = $true
                if ($s.name -eq 'api') { Write-Host "[api] Serving $($s.url)" -ForegroundColor Cyan }
                else { Write-Host "[web] VITE ready · $($s.url)" -ForegroundColor Cyan }
            }
            if (-not $s.proc.HasExited) { $anyAlive = $true }
            elseif ($s.outEof -and $s.errEof -and -not $exited) { $exited = $s }
        }
        # 两者都 ready 后打 footer（一次）
        if (-not $footerPrinted -and ($supervised | Where-Object { -not $_.ready } | Measure-Object).Count -eq 0) {
            Write-Host "[dev] Ctrl+C stops api + web" -ForegroundColor DarkGray
            $footerPrinted = $true
        }
        # 任一进程退出且管道已 drain → 保存其退出码，跳出去清理
        if ($exited) {
            $desiredExitCode = $exited.proc.ExitCode   # taskkill 之前先存，避免被 $LASTEXITCODE 覆盖
            Write-Host "[$($exited.name)] exited (code $desiredExitCode)" -ForegroundColor Yellow
            break
        }
        if (-not $anyAlive) { break }
        Start-Sleep -Milliseconds 50
    }
}
finally {
    # 幂等清理两棵树（含 reloader/HMR 派生的子进程）
    foreach ($s in $supervised) {
        if ($s.proc -and -not $s.proc.HasExited) { Stop-Tree $s.proc.Id }
    }
    # 清理后端口复查（taskkill /T 对已孤立后代可能漏；硬保证需 Job Object，本期兜底告警）
    # 关键：只查本脚本监督过的端口（遍历 $supervised）——仅后端模式下 $supervised 只有 api，
    # 故绝不复查 :5173，避免误伤用户独立运行的 Vite。切勿改成固定 :5000/:5173。
    Start-Sleep -Milliseconds 300
    foreach ($s in $supervised) {
        if (Test-Listening $s.port) { Write-Host "[dev] ⚠ 端口 :$($s.port) 仍被占用，可能有孤儿进程" -ForegroundColor Yellow }
    }
}

# 正常/异常退出走 $desiredExitCode；Ctrl+C 路径在中断处设 $desiredExitCode=130（见上方要点）
exit $desiredExitCode
```

> **Ctrl+C → `$desiredExitCode=130`**：PowerShell 在 Ctrl+C 时会执行 `finally`（清理跑到），`finally` **只清理、不改写 `$desiredExitCode`**。为显式保证 130：在脚本顶部 `$desiredExitCode=0` 之外，注册 `[Console]::CancelKeyPress`（或在 try 循环检测取消）→ 设 `$script:desiredExitCode = 130` + 触发跳出循环 → finally 清理 → 末尾 `exit $desiredExitCode`。**实现要点（实施者对照真实 pwsh 验证）**：若 Ctrl+C 打断后控制权不回到末尾 `exit`，则在 CancelKeyPress 处理里设码后让循环 break。以验收项②（Ctrl+C 后退出码=130 且无残留）为准迭代。

- [ ] **Step 2: 语法解析检查**

Run: 同 Task 1 Step 2。Expected: `parse OK`。

- [ ] **Step 3: Commit（实现就绪，进入验收）**

```bash
git add dev.ps1
git commit -m "feat(dev): dev.ps1 进程监督主循环 + 信号清理 + 退出码传播"
```

---

## Task 4: 手动集成验收（9 项，迭代到全过）

**Files:** Modify `dev.ps1`（验收中发现的修复）

> 逐项验收；任一不过 → 改 `dev.ps1` → 重跑该项。每项前确保 :5000/:5173 无残留（`Get-NetTCPConnection -LocalPort 5000,5173 -State Listen`）。

- [ ] **1. 双进程 + 双前缀 + 地址块**：`./dev.ps1 -Frontend` → `[api]`/`[web]` 行**实时**交替出现；就绪后打 `[api] Serving …` / `[web] VITE ready · …/ui/` / `[dev] Ctrl+C stops api + web`。
- [ ] **2. Ctrl+C 全灭 + 130**：Ctrl+C → 两进程树消失；事后 `Get-NetTCPConnection -LocalPort 5000,5173 -State Listen` 空；`$LASTEXITCODE`（或 `echo $?` 后查）= 130。
- [ ] **3. 手 kill 其一 → 联动**：另开终端 `taskkill /F /PID <api或web pid>` → 脚本打 `[name] exited (code N)` → 清理另一个 → 脚本退出码 = 该子进程码。
- [ ] **4. 端口预占不杀**：先占 :5000（如另起一个 server）→ `./dev.ps1` → 打 `⚠ :5000 占用 (PID …)，请先处理` 退出；**原占用进程仍存活**（`Get-Process -Id <pid>` 仍在）。
- [ ] **5. 仅后端**：`./dev.ps1`（无 -Frontend）→ 仅 `[api]` 前缀；Ctrl+C 停；行为同现状。
- [ ] **6. reloader 子进程也被清**：`./dev.ps1 -Frontend` 起来后改一个 `.py` 触发 Flask reloader 生成新子进程 → Ctrl+C → `Get-NetTCPConnection -LocalPort 5000 -State Listen` 空（taskkill /T 整树）。
- [ ] **7. Vite HMR 后清理**：改一个 `frontend/src/*.vue` 触发 HMR → Ctrl+C → :5173 无残留。
- [ ] **8. 连续起停 3 次**：`./dev.ps1 -Frontend` → Ctrl+C，重复 3 次；每次起得来、停得净，无 :5000/:5173 残留。
- [ ] **9. 语法检查**：Parser ParseFile 返回无 error（同 Task 1 Step 2）。
- [ ] **10. 独立 Vite 占 :5173 + 仅后端不误伤**：另起独立进程监听 :5173 → `./dev.ps1`（**无** -Frontend）起停 → 全程不杀该进程、清理后**不**对 :5173 告警（只复查 :5000）；该独立进程仍存活。

- [ ] **Step: 验收全过后 Commit（若有修复）**

```bash
git add dev.ps1
git commit -m "fix(dev): dev.ps1 监督器集成验收修复（Ctrl+C 130/树清理/边界）"
```

- [ ] **收尾**：按 `superpowers:finishing-a-development-branch`：push `feat/dev-ps1-supervisor` → PR → CI（仅语法/无关后端）→ squash merge。（dev.ps1 不进 CI 测试矩阵；PR 主要是走流程 + 留痕。）

---

## Self-Review 笔记

- **Spec 覆盖**：§1 退出码闸 + pg_isready ready 文案(T2) / §2 Process+ReadLineAsync 主循环 + EOF($null 停续发) + drain(outEof&&errEof 后才报退出) + 就绪并入循环 + npm.cmd + PYTHONUNBUFFERED + FORCE_COLOR + Vite --host/--strictPort/--clearScreen(no --color)(T1/T3) / §3 端口预检不杀 + TCP 就绪打址 + Ctrl+C 130 + 退出码先存后 taskkill + 幂等清理 + 端口复查 + 仅后端(T3) / §4 Parser 语法检查(每 task) + 9 项手动验收(T4)。全覆盖。
- **已知迭代点**：Ctrl+C → 130 的精确实现（finally 必跑，但退出码显式化需对照真实 pwsh，T3 Step1 已标注 + T4 验收项②钉死）；ReadLineAsync `IsCompleted`/`$null` EOF 语义以真实执行为准微调。
- **无占位**：辅助函数、前半、监督循环、清理 finally 全是完整 PowerShell；验收项给出确切命令。
- **类型/命名一致**：`Get-ListeningPid`/`Test-Listening`/`Stop-Tree`/`Start-Supervised`(T1) 在 T2/T3 一致调用；`$supervised` entry 字段（name/proc/port/url/ready/outTask/errTask/outEof/errEof）跨 T3 一致。
- **Windows-only**：`Get-NetTCPConnection`/`taskkill`/`npm.cmd` 均 Windows；spec 已声明不跨平台。
