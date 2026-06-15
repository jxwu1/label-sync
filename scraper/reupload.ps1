# scraper/reupload.ps1
# 补传工具: 当 run_weekly 抓取/脱敏/manifest 全成功、仅"上传"步骤失败时
# (典型: 上传窗口内 Flask 被 Coolify 部署打掉 → "no available server"),
# 复用 sanitized/ 里已脱敏的文件重新上传 + 触发服务端重算, **不重抓**。
#
# 严格镜像 run_weekly.ps1 的上传 + staging自清 + 刷新逻辑 (categories→forecast→heartbeat)。
# 用法: cd scraper; .\reupload.ps1

$ErrorActionPreference = "Stop"

$envPath      = Join-Path $PSScriptRoot ".env"
$logDir       = Join-Path $PSScriptRoot "logs"
$sanitizedDir = Join-Path $PSScriptRoot "sanitized"
$uploadedDir  = Join-Path $PSScriptRoot "uploaded"
$stagingDir   = Join-Path $PSScriptRoot "staging"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $uploadedDir | Out-Null

$ts  = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir "reupload_$ts.log"

function Log {
    param([string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $Message"
    $line | Tee-Object -FilePath $log -Append | Out-Null
    Write-Host $line
}

function Read-EnvVar {
    param([string]$Key)
    if (-not (Test-Path $envPath)) { throw "scraper/.env 不存在: $envPath" }
    $match = Get-Content $envPath | Where-Object { $_ -match "^$Key=" }
    if (-not $match) { throw "scraper/.env 缺 $Key" }
    return ($match -split "=", 2)[1].Trim()
}

try {
    Log "=== reupload 开始 (复用 sanitized/, 不重抓) ==="
    $uploadUrl   = Read-EnvVar "UPLOAD_URL"
    $uploadToken = Read-EnvVar "UPLOAD_TOKEN"
    Log "upload_url: $uploadUrl"

    $files = Get-ChildItem -Path $sanitizedDir -Filter "*.parquet" -File
    if ($files.Count -eq 0) { throw "sanitized/ 没有 parquet, 没东西可补传" }
    Log "待补传 $($files.Count) 个文件"

    $thisRunDir = Join-Path $uploadedDir $ts
    New-Item -ItemType Directory -Force -Path $thisRunDir | Out-Null

    foreach ($f in $files) {
        Log "上传 $($f.Name)"
        $resp = curl.exe --silent --show-error -X POST `
            -H "X-Upload-Token: $uploadToken" `
            -F "file=@$($f.FullName)" `
            $uploadUrl 2>&1
        Log "← $resp"
        if ($LASTEXITCODE -ne 0) { throw "curl 上传失败: $($f.Name), 退出 $LASTEXITCODE" }
        if ($resp -notmatch '"ok":\s*true') { throw "上传返回非 ok: $($f.Name) → $resp" }
        Move-Item -Path $f.FullName -Destination $thisRunDir
    }
    Log "=== 上传完成, $($files.Count) 文件挪到 $thisRunDir ==="

    # staging 自清 (镜像 run_weekly: 防 staging 累积历史; _cache 保留)
    if (Test-Path $stagingDir) {
        $stagingDest = Join-Path $thisRunDir "staging"
        New-Item -ItemType Directory -Force -Path $stagingDest | Out-Null
        $stagingFiles = Get-ChildItem -Path $stagingDir -File | Where-Object {
            $_.Name -match '^(events_|inventory_snapshot_|product_master_)'
        }
        foreach ($sf in $stagingFiles) { Move-Item -Path $sf.FullName -Destination $stagingDest }
        Log "staging 自清: 挪走 $($stagingFiles.Count) 个文件 → $stagingDest (_cache 保留)"
    } else {
        Log "staging 自清: 跳过 (目录不存在)"
    }

    # 触发服务端重算 (镜像 run_weekly: 分类→预测→心跳; 心跳最后, 整链成功才打存活信号)
    $refreshBase = $uploadUrl -replace '/data/upload/?$', ''
    Log "=== 触发分类 + 预测刷新 (base: $refreshBase) ==="
    foreach ($r in @("categories/recompute", "forecast/refresh", "scrape/heartbeat")) {
        Log "→ 刷新 $r"
        $resp = curl.exe --silent --show-error --max-time 600 -X POST `
            -H "X-Upload-Token: $uploadToken" `
            "$refreshBase/$r" 2>&1
        Log "← $resp"
        if ($LASTEXITCODE -ne 0) { throw "$r 刷新失败 (curl 退出 $LASTEXITCODE)" }
        if ($resp -notmatch '"ok":\s*true') { throw "$r 刷新返回非 ok: $resp" }
    }
    Log "=== 补传 + 刷新完成 ==="
    exit 0
}
catch {
    Log "!!! 补传失败: $_"
    Log ($_ | Out-String)
    exit 1
}
