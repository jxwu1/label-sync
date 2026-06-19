#!/usr/bin/env pwsh
# 本地开发一键启动：本地 PostgreSQL（Docker）+ 热重载 Flask（+ 可选 Vite 前端）。
# 零依赖进程监督器：Flask/Vite 同终端、[api]/[web] 前缀逐行实时输出、Ctrl+C 关两进程树。
#
#   ./dev.ps1              # 仅起后端（监督 api）
#   ./dev.ps1 -Frontend    # 同时起前端 Vite（:5173），监督 api + web
#
# 起来后改 .py / templates/*.html 存盘即自动重载。数据用本地 PG（:5433）；
# 要灌线上真实数据先跑 tools/pull_prod_db.py。Windows-only（进程树清理走 taskkill /T）。
param(
    [switch]$Frontend
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# ---- 辅助函数 ----

# 端口被谁监听 → 返回 PID，否则 $null
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

# 启动一个 stdout/stderr 重定向的进程
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

# 排空一条流当前已就绪的所有行（加前缀打印）；$null=EOF 置标志停续发。返回是否打了行。
function Drain-Stream($entry, [string]$which) {
    $did = $false
    $eofProp = "$($which)Eof"; $taskProp = "$($which)Task"
    $reader = if ($which -eq 'out') { $entry.proc.StandardOutput } else { $entry.proc.StandardError }
    while (-not $entry.$eofProp -and $entry.$taskProp.IsCompleted) {
        $line = $entry.$taskProp.Result
        if ($null -eq $line) { $entry.$eofProp = $true }
        else { Write-Host "[$($entry.name)] $line"; $entry.$taskProp = $reader.ReadLineAsync(); $did = $true }
    }
    return $did
}

# ---- 1. 起本地 PostgreSQL 17 ----
# 非零不立即退出：dev-pg 现为持久旧容器（项目标签/卷可能漂移，见 backlog: dev-pg 命名卷迁移），
# `up -d` 会因名字冲突返回非零，但同名 PG 多半在跑。pg_isready 兜底续行——它只证明「某个同名 PG 活着」，
# 不证明目标 compose 配置已应用；根治请单独做旧容器迁移，勿把环境残留当常规启动路径。
docker compose -f docker-compose.dev.yml up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "[dev] ! docker compose up 非零 (exit $LASTEXITCODE)——多半是 dev-pg 旧容器项目标签/卷漂移（孤儿容器）" -ForegroundColor Yellow
    Write-Host "[dev]   暂以 pg_isready 兜底续行；根治：单独迁移容器（命名卷 + 固定 project name，见 backlog）" -ForegroundColor DarkYellow
}

# ---- 2. 等 PG 真正可接受查询（pg_isready 重试最多 30s；权威就绪闸；非零是预期重试，不退出） ----
# 用 `docker exec <container_name>` 而非 `docker compose exec <service>`：容器名固定
# (compose container_name: label-sync-dev-pg)，对 compose project 追踪冲突免疫；
# `docker compose exec` 在容器名冲突/孤儿态下会报 "service not running"。
$pgReady = $false
for ($i = 0; $i -lt 30; $i++) {
    docker exec label-sync-dev-pg pg_isready -U dev -d label_sync 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $pgReady = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $pgReady) {
    Write-Host "[dev] x PostgreSQL 30s 内未就绪" -ForegroundColor Red
    exit 1
}
Write-Host "[dev] PostgreSQL ready - :5433" -ForegroundColor Green

# ---- 3. 指向本地 PG + 打开热重载 ----
$env:DATABASE_URL = 'postgresql+psycopg://dev:devpass@localhost:5433/label_sync'
$env:LABEL_SYNC_DEBUG = '1'

# ---- 4. 同步 schema（幂等） ----
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "[dev] x alembic upgrade 失败 (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "[dev] Alembic upgrade complete" -ForegroundColor Green

# ---- 5. 启动并监督进程 ----
# 端口预检查：占用则报 PID 退出，不杀（被占的原进程必须存活）
$apiPid = Get-ListeningPid 5000
if ($apiPid) { Write-Host "[dev] ! :5000 占用 (PID $apiPid)，请先处理" -ForegroundColor Yellow; exit 1 }
if ($Frontend) {
    $webPid = Get-ListeningPid 5173
    if ($webPid) { Write-Host "[dev] ! :5173 占用 (PID $webPid)，请先处理" -ForegroundColor Yellow; exit 1 }
}

# Ctrl+C：纯 C# Console.CancelKeyPress 处理器（不经 PS runspace，避开 scriptblock no-runspace 坑）。
# Install 幂等（重复调不叠加）；保存 delegate，finally 调 Uninstall 卸载，防同会话多次运行累积处理器。
if (-not ([System.Management.Automation.PSTypeName]'DevSupervisor.CtrlC').Type) {
    Add-Type @'
namespace DevSupervisor {
    public static class CtrlC {
        public static volatile bool Requested = false;
        private static System.ConsoleCancelEventHandler _handler;
        public static void Install() {
            if (_handler != null) { return; }
            _handler = delegate (object s, System.ConsoleCancelEventArgs e) { e.Cancel = true; Requested = true; };
            System.Console.CancelKeyPress += _handler;
        }
        public static void Uninstall() {
            if (_handler != null) { System.Console.CancelKeyPress -= _handler; _handler = null; }
        }
    }
}
'@
}

# 退出码单一真源：Ctrl+C=130 / 子进程异常=其 ExitCode / 启动或就绪失败=非零。finally 只清理不改写它。
$desiredExitCode = 0
$footerPrinted = $false
$readyTimeoutSec = 30
$supervised = [System.Collections.ArrayList]::new()   # 在 try 外声明，finally 才能清理已启动的进程

try {
    [DevSupervisor.CtrlC]::Requested = $false
    [DevSupervisor.CtrlC]::Install()

    # 进程启动纳入 try：web 启动/ReadLineAsync 任一步抛错，已起的 api 仍会进 finally 清理（不残留 :5000）
    $apiProc = Start-Supervised 'python' @('-u', 'server.py') $root $null   # 只用 -u，不叠加 PYTHONUNBUFFERED
    [void]$supervised.Add(@{
            name = 'api'; proc = $apiProc; port = 5000; url = 'http://127.0.0.1:5000'; ready = $false
            outTask = $apiProc.StandardOutput.ReadLineAsync(); errTask = $apiProc.StandardError.ReadLineAsync()
            outEof = $false; errEof = $false
        })
    if ($Frontend) {
        # 经 cmd.exe /c npm 拉起：.NET 直跑 npm.cmd 会让 npm %~dp0 解析错乱
        # （去 frontend\node_modules\npm\ 找 npm 自身 → MODULE_NOT_FOUND）。cmd 为被监督进程，node/vite 子进程，taskkill /T 杀整树。
        $webProc = Start-Supervised 'cmd.exe' `
            @('/c', 'npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--strictPort', '--clearScreen', 'false') `
            (Join-Path $root 'frontend') @{ FORCE_COLOR = '1' }
        [void]$supervised.Add(@{
                name = 'web'; proc = $webProc; port = 5173; url = 'http://localhost:5173/ui/'; ready = $false
                outTask = $webProc.StandardOutput.ReadLineAsync(); errTask = $webProc.StandardError.ReadLineAsync()
                outEof = $false; errEof = $false
            })
    }

    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    while ($true) {
        # Ctrl+C 置顶检查，优先于子进程退出处理
        if ([DevSupervisor.CtrlC]::Requested) {
            $desiredExitCode = 130
            Write-Host "`n[dev] Ctrl+C - stopping…" -ForegroundColor DarkGray
            break
        }

        $didWork = $false
        $exited = $null
        foreach ($s in $supervised) {
            # 一次排空两条流当前已就绪的全部行（不再每流每 tick 只读一行 → 消除逐行轮流挤牙膏）
            if (Drain-Stream $s 'out') { $didWork = $true }
            if (Drain-Stream $s 'err') { $didWork = $true }
            # 就绪探测并入循环（不阻塞）：实际监听后才打地址
            if (-not $s.ready -and (Test-Listening $s.port)) {
                $s.ready = $true
                if ($s.name -eq 'api') { Write-Host "[api] Serving $($s.url)" -ForegroundColor Cyan }
                else { Write-Host "[web] VITE ready - $($s.url)" -ForegroundColor Cyan }
            }
            # 退出且管道已 drain 到 EOF → 候选退出（不再凭「全死」early-break，保尾部日志 + 真实退出码）
            if ($s.proc.HasExited -and $s.outEof -and $s.errEof -and -not $exited) { $exited = $s }
        }

        # 全部 ready 后打 footer（一次）
        if (-not $footerPrinted -and ($supervised | Where-Object { -not $_.ready } | Measure-Object).Count -eq 0) {
            Write-Host "[dev] Ctrl+C stops $(($supervised | ForEach-Object { $_.name }) -join ' + ')" -ForegroundColor DarkGray
            $footerPrinted = $true
        }

        # 任一进程退出且已 drain → 先存退出码（在任何 taskkill 之前），跳出清理
        if ($exited) {
            $desiredExitCode = $exited.proc.ExitCode
            Write-Host "[$($exited.name)] exited (code $desiredExitCode)" -ForegroundColor Yellow
            break
        }

        # 就绪超时：进程活着但 ~30s 仍不监听端口 → 失败退出，避免永久挂起
        if ($sw.Elapsed.TotalSeconds -gt $readyTimeoutSec) {
            $stuck = @($supervised | Where-Object { -not $_.ready -and -not $_.proc.HasExited })
            if ($stuck.Count -gt 0) {
                $desiredExitCode = 1
                Write-Host "[dev] x 就绪超时 (${readyTimeoutSec}s)：$(($stuck | ForEach-Object { $_.name }) -join ', ') 未监听端口" -ForegroundColor Red
                break
            }
        }

        # 有输出就立刻再循环（全速刷新）；空闲才小睡防 busy-CPU
        if (-not $didWork) { Start-Sleep -Milliseconds 25 }
    }
}
finally {
    [DevSupervisor.CtrlC]::Uninstall()
    # 幂等清理两棵树（含 reloader/HMR 派生的子进程）；finally 不改写 $desiredExitCode
    foreach ($s in $supervised) {
        if ($s.proc -and -not $s.proc.HasExited) { Stop-Tree $s.proc.Id }
    }
    # 清理后端口复查：只查本脚本监督过的端口（仅后端时 $supervised 只有 api → 绝不查 :5173，
    # 避免误伤用户独立运行的 Vite）。切勿改成固定 :5000/:5173。
    Start-Sleep -Milliseconds 300
    foreach ($s in $supervised) {
        if (Test-Listening $s.port) {
            Write-Host "[dev] ! 端口 :$($s.port) 仍被占用，可能有孤儿进程" -ForegroundColor Yellow
        }
    }
}

exit $desiredExitCode
