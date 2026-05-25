$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\Dev\label-sync\scraper\run_weekly.ps1"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 14:00
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd
Register-ScheduledTask -TaskName "label-sync-weekly-scrape" -Action $action -Trigger $trigger -Principal $principal -Settings $settings
Write-Host "`n注册完成. 验证:"
Get-ScheduledTask -TaskName "label-sync-weekly-scrape" | Format-List TaskName, State
Write-Host "按任意键关闭..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
