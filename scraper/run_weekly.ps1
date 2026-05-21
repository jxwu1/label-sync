# scraper/run_weekly.ps1
# 周一 14:00 (希腊时间) 由 Windows Task Scheduler 触发.
# 串联: sales scraper → purchase scraper → inventory scraper → sanitize → upload
#
# 失败任何一步都立即退出 (exit code != 0), Task Scheduler 会记录失败.
# 日志全在 scraper/logs/run_weekly_<ts>.log

$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repo ".venv\Scripts\python.exe"
$envPath = Join-Path $PSScriptRoot ".env"
$logDir = Join-Path $PSScriptRoot "logs"
$sanitizedDir = Join-Path $PSScriptRoot "sanitized"
$uploadedDir = Join-Path $PSScriptRoot "uploaded"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $uploadedDir | Out-Null

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir "run_weekly_$ts.log"

function Log {
    param([string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $Message"
    $line | Tee-Object -FilePath $log -Append | Out-Null
    Write-Host $line
}

function Read-EnvVar {
    param([string]$Key)
    if (-not (Test-Path $envPath)) {
        throw "scraper/.env 不存在: $envPath"
    }
    $match = Get-Content $envPath | Where-Object { $_ -match "^$Key=" }
    if (-not $match) { throw "scraper/.env 缺 $Key" }
    return ($match -split "=", 2)[1].Trim()
}

function Run-Step {
    # NOTE: 参数名不能用 $Args, 跟 PowerShell 函数自动变量冲突, 传值会丢
    param([string]$Name, [string]$Script, [string[]]$ScriptArgs = @())
    Log "→ $Name $($ScriptArgs -join ' ')"
    & $python $Script @ScriptArgs 2>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) {
        throw "$Name 失败 (exit $LASTEXITCODE)"
    }
}

try {
    Log "=== run_weekly 开始 ==="
    Log "repo: $repo"
    Log "python: $python"

    if (-not (Test-Path $python)) { throw ".venv 没装好: $python 不存在" }
    if (-not (Test-Path $envPath)) { throw "scraper/.env 不存在, 从 .env.example 复制并填值" }

    $uploadUrl = Read-EnvVar "UPLOAD_URL"
    $uploadToken = Read-EnvVar "UPLOAD_TOKEN"
    Log "upload_url: $uploadUrl"

    # 时间窗口: 最近 7 天 (覆盖上周 + 当天, 跟服务器 dedup 兼容)
    $today = (Get-Date).ToString("yyyy-MM-dd")
    $weekAgo = (Get-Date).AddDays(-7).ToString("yyyy-MM-dd")
    Log "时间窗口: $weekAgo → $today"

    # === 抓取 ===
    Run-Step "sales_scraper"    (Join-Path $PSScriptRoot "sales_scraper.py")    -ScriptArgs @("--from", $weekAgo, "--to", $today)
    Run-Step "purchase_scraper" (Join-Path $PSScriptRoot "purchase_scraper.py") -ScriptArgs @("--from", $weekAgo, "--to", $today)
    Run-Step "inventory_scraper" (Join-Path $PSScriptRoot "inventory_scraper.py")

    # 月度: 本月第一个周一才跑 product master (DayOfMonth <= 7).
    # 抓产品总档全量, 包括 "标了供应商但还没采购过" 的 SKU, 用来补 stockpile.supplier_id.
    $dayOfMonth = (Get-Date).Day
    if ($dayOfMonth -le 7) {
        Log "本月第一个周一 (day=$dayOfMonth), 跑 product_master_scraper"
        Run-Step "product_master_scraper" (Join-Path $PSScriptRoot "product_master_scraper.py")
    } else {
        Log "跳过 product_master_scraper (day=$dayOfMonth, 非本月第一周)"
    }

    # === 脱敏 ===
    Run-Step "sanitize" (Join-Path $PSScriptRoot "sanitize.py") @()

    # === 上传 ===
    $files = Get-ChildItem -Path $sanitizedDir -Filter "*.parquet" -File
    if ($files.Count -eq 0) {
        throw "sanitized/ 没找到 parquet, 链路上游有静默失败?"
    }
    Log "待上传 $($files.Count) 个文件"

    $thisRunDir = Join-Path $uploadedDir $ts
    New-Item -ItemType Directory -Force -Path $thisRunDir | Out-Null

    foreach ($f in $files) {
        Log "上传 $($f.Name)"
        $resp = curl.exe --silent --show-error -X POST `
            -H "X-Upload-Token: $uploadToken" `
            -F "file=@$($f.FullName)" `
            $uploadUrl 2>&1
        Log "← $resp"
        if ($LASTEXITCODE -ne 0) {
            throw "curl 上传失败: $($f.Name), 退出 $LASTEXITCODE"
        }
        if ($resp -notmatch '"ok":\s*true') {
            throw "上传返回非 ok: $($f.Name) → $resp"
        }
        # 成功 → 挪到 uploaded/<ts>/, 下次不再传
        Move-Item -Path $f.FullName -Destination $thisRunDir
    }

    Log "=== 完成: $($files.Count) 文件上传, 挪到 $thisRunDir ==="
    exit 0
}
catch {
    Log "!!! 失败: $_"
    Log "!!! 完整 trace:"
    Log ($_ | Out-String)
    exit 1
}
