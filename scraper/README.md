# scraper — boson ERP 数据抓取

本地脚本, 不部署到服务器. 从 boson ERP 抓销售 / 采购 / (TODO) 库存快照,
输出 parquet 给 `tools/import_parquet.py` 入库.

## 首次配置

```bash
cd scraper
cp .env.example .env          # 改里面的 BOSON_BASE_URL / 输出目录
cp cookie.txt.example cookie.txt
# 编辑 cookie.txt, 粘贴 PHPSESSID
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

## TODO

- [ ] Step 2.2 迁移 sales / purchase 脚本, env var 化
- [ ] Step 2.3 新写 inventory_scraper.py (输出当前库存快照)
- [ ] Step 2.4 本地 cron 触发器 + 推送到服务器入库
- [ ] cookie 失效自动告警
