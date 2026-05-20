# scraper — boson ERP 数据抓取

本地脚本, 不部署到服务器. 从 boson ERP 抓销售 / 采购 / (TODO) 库存快照,
输出 parquet 给 `tools/import_parquet.py` 入库.

## 首次配置

```bash
# 1. 装依赖 (除主项目依赖外, scraper 还需 requests / dateutil)
pip install -r scraper/requirements.txt

# 2. 配置
cd scraper
cp .env.example .env          # 改里面的 BOSON_BASE_URL / 输出目录
cp cookie.txt.example cookie.txt
# 编辑 cookie.txt, 粘贴 PHPSESSID
```

## 用法

```bash
# 销售明细 (默认最近 1 年)
python scraper/sales_scraper.py
python scraper/sales_scraper.py --from 2023-01-01 --to 2026-05-20

# 采购明细
python scraper/purchase_scraper.py --from 2023-01-01 --to 2026-05-20
```

`.env` 和 `cookie.txt` 已经在根 `.gitignore` 里, **不会被提交**.

## Cookie 维护

PHPSESSID 失效时:
1. 浏览器登录 boson
2. F12 → Application → Cookies → 复制 PHPSESSID
3. 替换 `scraper/cookie.txt` 一行内容

抓取脚本响应 < 50KB 或返回 `系统已注销` 时, 表示 cookie 过期, 退出并告警 (TODO).

## 文件结构

```
scraper/
├── .env.example          # commit, 配置模板
├── cookie.txt.example    # commit, cookie 维护说明
├── .env                  # 本地, gitignored
├── cookie.txt            # 本地, gitignored
├── staging/              # 抓取中间产物, gitignored
├── README.md             # 本文件
├── sales_scraper.py      # (Step 2.2) 销售抓取, 从 D:\python\pythonProject 迁移
├── purchase_scraper.py   # (Step 2.2) 采购抓取
└── inventory_scraper.py  # (Step 2.3) 库存快照抓取 (新写)
```

## 自动化 (run_weekly.ps1 + Windows Task Scheduler)

每周一 14:00 自动跑全链路 (抓取 → 脱敏 → 上传):

```powershell
# 一次性: 注册 Task Scheduler (管理员 PowerShell)
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\Dev\label-sync\scraper\run_weekly.ps1"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 14:00
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd
Register-ScheduledTask -TaskName "label-sync-weekly-scrape" `
  -Action $action -Trigger $trigger -Principal $principal -Settings $settings
```

手动测试 (登记前先跑一遍验证):

```powershell
.\scraper\run_weekly.ps1
```

输出在 `scraper/logs/run_weekly_<ts>.log`. 成功后:
- `scraper/sanitized/*.parquet` → 挪到 `scraper/uploaded/<ts>/`
- 任一步失败 exit 1, Task Scheduler "上次运行结果" 显示非 0

## TODO

- [x] Step 2.2 迁移 sales / purchase 脚本, env var 化
- [x] Step 2.3 inventory_scraper.py 输出库存快照
- [x] Step 2.4 sanitize.py 脱敏
- [x] Step 2.5 run_weekly.ps1 cron wrapper
- [ ] cookie 失效自动告警 (响应 < 50KB 时邮件 / 桌面通知)
