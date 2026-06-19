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

# ---- 1. 起本地 PostgreSQL 17 ----
# 非零不立即退出：dev-pg 是持久容器，已存在时 `up -d` 会因名字冲突返回非零，但 PG 其实在跑。
# 真正的就绪权威闸是下面的 pg_isready——它没过才算 PG 不可用。
docker compose -f docker-compose.dev.yml up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "[dev] ! docker compose up 非零 (exit $LASTEXITCODE)——容器可能已存在/冲突；以 pg_isready 为准继续" -ForegroundColor Yellow
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

# 被监督进程表（仅后端时只含 api）
$supervised = [System.Collections.ArrayList]::new()
$apiProc = Start-Supervised 'python' @('-u', 'server.py') $root $null   # 只用 -u，不叠加 PYTHONUNBUFFERED
[void]$supervised.Add(@{
        name = 'api'; proc = $apiProc; port = 5000; url = 'http://127.0.0.1:5000'; ready = $false
        outTask = $apiProc.StandardOutput.ReadLineAsync(); errTask = $apiProc.StandardError.ReadLineAsync()
        outEof = $false; errEof = $false
    })
if ($Frontend) {
    # 经 cmd.exe /c npm 拉起：.NET Process 直跑 npm.cmd 会让 npm 的 %~dp0 解析错乱
    # （去 frontend\node_modules\npm\ 找 npm 自身 → MODULE_NOT_FOUND）。cmd /c 从 PATH 正确解析 npm。
    # cmd.exe 是被监督进程，node/vite 是其子进程，taskkill /T 杀整树。
    $webProc = Start-Supervised 'cmd.exe' `
        @('/c', 'npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--strictPort', '--clearScreen', 'false') `
        (Join-Path $root 'frontend') @{ FORCE_COLOR = '1' }
    [void]$supervised.Add(@{
            name = 'web'; proc = $webProc; port = 5173; url = 'http://localhost:5173/ui/'; ready = $false
            outTask = $webProc.StandardOutput.ReadLineAsync(); errTask = $webProc.StandardError.ReadLineAsync()
            outEof = $false; errEof = $false
        })
}

# 退出码单一真源：Ctrl+C=130 / 子进程异常=其 ExitCode / 启动失败=非零。finally 只清理不改写它。
$desiredExitCode = 0
$footerPrinted = $false

# Ctrl+C：用纯 C# Console.CancelKeyPress 处理器（不经 PS runspace，避开 scriptblock no-runspace 坑）。
# e.Cancel=$true 阻止默认终止 → 主循环轮询 volatile 标志 → 优雅 break + finally 清理 + exit 130。
if (-not ([System.Management.Automation.PSTypeName]'DevSupervisor.CtrlC').Type) {
    Add-Type @'
namespace DevSupervisor {
    public static class CtrlC {
        public static volatile bool Requested = false;
        public static void Install() {
            System.Console.CancelKeyPress += delegate (object s, System.ConsoleCancelEventArgs e) {
                e.Cancel = true;
                Requested = true;
            };
        }
    }
}
'@
}
[DevSupervisor.CtrlC]::Requested = $false
[DevSupervisor.CtrlC]::Install()

try {
    while ($true) {
        # Ctrl+C 检测（C# 处理器置的 volatile 标志；置顶检查，优先于子进程退出处理）
        if ([DevSupervisor.CtrlC]::Requested) {
            $desiredExitCode = 130
            Write-Host "`n[dev] Ctrl+C - stopping…" -ForegroundColor DarkGray
            break
        }

        $anyAlive = $false
        $exited = $null
        foreach ($s in $supervised) {
            # stdout：完成行加前缀；$null=EOF 停续发（防空转）
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
            # 就绪探测并入循环（不阻塞）：实际监听后才打地址
            if (-not $s.ready -and (Test-Listening $s.port)) {
                $s.ready = $true
                if ($s.name -eq 'api') { Write-Host "[api] Serving $($s.url)" -ForegroundColor Cyan }
                else { Write-Host "[web] VITE ready - $($s.url)" -ForegroundColor Cyan }
            }
            if (-not $s.proc.HasExited) { $anyAlive = $true }
            # 退出且管道已 drain 到 EOF → 候选退出
            elseif ($s.outEof -and $s.errEof -and -not $exited) { $exited = $s }
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
        if (-not $anyAlive) { break }
        Start-Sleep -Milliseconds 50
    }
}
finally {
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
