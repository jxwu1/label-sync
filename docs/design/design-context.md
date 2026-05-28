# label-sync 前端设计上下文

> 新对话开始时把这个文件发给 Claude，附上要设计的模块名称即可。

---

## 项目背景

label-sync 是一个基于 Flask 的 ERP 库存标签处理系统（内部工具，单用户），正在做前端视觉全面重构。技术栈：Flask + Jinja 模板 + Alpine.js + Tailwind CSS v4 + DaisyUI v5。

## 设计方向

Linear App 风格内部工具 UI。双主题（dark / light），红色功能强调色。
信息密度对标 Linear：紧凑但有呼吸。
审美关键词：精密、硬朗、有秩序、有辨识度，每一条线都有理由。

参考：Linear App (dark dashboard)、Raycast、Warp Terminal、Supabase Dashboard。

## 审美画像（核心）

- 精密工具主义——德系理性骨架 + 日系千禧精致
- 秩序高于一切，统一即品质，流畅即审美
- 硬朗直线优先，直角或极小统一圆角（4/6/8px）
- 底色黑/白果断二选一，最多一个功能性强调色（红）
- 排版：超大标题 + 极细正文，等宽数字，字号层级果断
- 动画：ease、fade + translate，无弹跳/弹性
- 交互：hover 微妙渐变，CTA 偏好文字链

---

## Design Token（完整色板）

### Dark 主题（默认）

```
背景层级：
--bg-0: #0A0A0B    页面底色
--bg-1: #111113    sidebar / header / 卡片
--bg-2: #19191C    输入框 / hover
--bg-3: #222225    active / 强调面
--bg-4: #2C2C30    scrollbar / 更深

边框：
--line: #2E2E32        主边框
--line-soft: #1F1F23   弱边框

文字：
--ink-0: #EDEDEF    主文字
--ink-1: #A0A0A6    次文字
--ink-2: #6E6E76    辅助 / placeholder
--ink-3: #4A4A52    最弱 / 标签

强调色：
--accent: #E5484D
--accent-dim: #C13B3F
--accent-glow: rgba(229,72,77,.15)
--accent-subtle: rgba(229,72,77,.08)
--accent-subtle-border: rgba(229,72,77,.25)
--on-accent: #FFFFFF

语义色：
--success: #46A758
--success-subtle: rgba(70,167,88,.08)
--success-subtle-border: rgba(70,167,88,.25)
--warn: #F5A623
--warn-subtle: rgba(245,166,35,.08)
--warn-subtle-border: rgba(245,166,35,.25)
--error: #E5484D
--error-subtle: rgba(229,72,77,.08)
--error-subtle-border: rgba(229,72,77,.25)
--info: #3E9DE6
--info-subtle: rgba(62,157,230,.08)
--info-subtle-border: rgba(62,157,230,.25)
```

### Light 主题

```
背景层级：
--bg-0: #FFFFFF
--bg-1: #F8F8F9
--bg-2: #F0F0F2
--bg-3: #E8E8EB
--bg-4: #DDDDE0

边框：
--line: #E0E0E3
--line-soft: #EBEBEE

文字：
--ink-0: #1A1A1E
--ink-1: #6B6B76
--ink-2: #9B9BA6
--ink-3: #C0C0C8

强调色：
--accent: #DC3545
--accent-dim: #B52A37
--accent-glow: rgba(220,53,69,.10)
--accent-subtle: rgba(220,53,69,.06)
--accent-subtle-border: rgba(220,53,69,.20)
--on-accent: #FFFFFF

语义色：
--success: #2D8A3E / subtle rgba(45,138,62,.06) / border rgba(45,138,62,.20)
--warn: #D4850C / subtle rgba(212,133,12,.06) / border rgba(212,133,12,.20)
--error: #DC3545 / subtle rgba(220,53,69,.06) / border rgba(220,53,69,.20)
--info: #2B7EC2 / subtle rgba(43,126,194,.06) / border rgba(43,126,194,.20)
```

---

## 间距 / 圆角 / 字体

```
间距（8pt grid）：
--sp-1: 4px  --sp-2: 8px  --sp-3: 12px  --sp-4: 16px
--sp-5: 20px --sp-6: 24px --sp-7: 32px  --sp-8: 40px

圆角：
--r-sm: 4px    按钮、输入框、pill、nav item
--r-md: 6px    卡片、table 容器
--r-lg: 8px    模态框、大面板

字体：
--sans: 'Inter', system-ui, -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif
--mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Consolas, monospace
--display: 'Space Grotesk', 'Inter', system-ui, sans-serif

字号：
--fs-xs: 10px  --fs-sm: 11px  --fs-md: 12px  --fs-base: 13px
--fs-lg: 15px  --fs-xl: 17px  --fs-2xl: 20px --fs-3xl: 24px --fs-4xl: 28px

动效：
--t-fast: .12s ease（hover、toggle）
--t-base: .2s ease（展开、切换）
```

---

## 组件模式速查

| 元素 | 样式规则 |
|------|---------|
| 面板 header | `pnl-hd`：编号标签（pnl-code，accent 底）+ 标题 + 副标题 + 右侧 pill/badge |
| 主按钮 | bg-accent, text-on-accent, border-accent-dim, rounded r-sm |
| 次按钮 | transparent, text-ink-1, border-line, hover bg-bg-2 |
| 数据表格 | thead bg-bg-1, th 大写 fs-xs ink-2, td border-b line-soft |
| 状态标签 pill | 2px 圆角, 10.5px, border + subtle bg（accent/success/warn/error/info/ghost）|
| 统计卡片 | bg-bg-1 border line-soft rounded-md p-4, label 大写 xs, value display 字体 |
| 数字/条码 | font-mono tabular-nums |
| 标题 | font-display, letter-spacing -0.02em |
| 间距 | 卡片内 p-4, 卡片间 gap-3, 页面 p-4 |

---

## 页面 shell 结构

所有页面共享：

```
sidebar (200px, bg-1) | main
                       |  header (48px, bg-1)
                       |  substrip (28px, bg-1, session 上下文)
                       |  content (scrollable, bg-0, p-4)
```

- sidebar：nav items 带图标 + 键盘快捷键，active 用 accent-subtle 底色
- header：面包屑（prefix ink-3 / sep / title ink-0 font-semibold）+ 状态 + 时钟
- substrip：SESSION / INPUT / STOCKPILE / TZ 等上下文信息
- 左下角：DARK / LIGHT 切换

---

## 已完成的设计

### 1. 总览 Dashboard（label-sync-dashboard-v2.html）
- stats 条（5 个卡片 + sparkline）
- 任务状态条（running/waiting/idle 三态）
- 左栏：最近动态 activity feed
- 右栏：数据质量 7 项摘要 + 系统状态

### 2. 标签处理（label-sync-labeling-final.html）
- 01 文件投递：简化 drop zone，拖入即处理
- 02 处理管线：5 阶段进度条（done ✓ / current accent / pending）
- 03 异常处理：三态切换
  - 空闲态：紧凑三行条（上次批次信息 + 处理结果摘要）
  - 活跃态：异常列表（severity 分级 HIGH/MED/LOW + 修正按钮）
  - 完成态：绿色 ✓ + 处理摘要（已修正/已确认/已忽略）
- 04 文件队列：文件列表 + 状态标签（DONE/RUN/QUEUE）+ 结果操作
- 05 扫描统计：四宫格（总条码+sparkline / 匹配率+bar / 异常+分级标签 / 新品）+ 最近新品条码
- 06 活动日志：mono 终端风格，彩色日志 + LIVE 脉冲

### 3. Resolution Center（label-sync-resolution-center.html）
- 独立的异常处理工作台视图
- Blocking Issues：卡片式，带 AI suggestion + 一键修复
- Batch Review：条码标签网格 + 批量操作
- 右栏：Current Batch 数字 + Match Rate + Auto Resolved 日志

---

## 待设计模块

3. 标签查重
4. 采购导入
5. 考勤台账
6. 货号历史
7. 数据质量
8. 数据健康
9. 老外客人
10. 补货决策
11. 系统管理（Stockpile 初始化/月度比对从标签处理页迁入）

---

## 禁止清单

- 禁止硬编码色值（必须用 token 变量）
- 禁止圆角超过 8px（除 pill 的 999px）
- 禁止弹跳/弹性动画
- 禁止渐变背景和 backdrop-filter
- 禁止 Inter 以外的新字体（除 JetBrains Mono 和 Space Grotesk）
- 禁止 Bootstrap / Material UI 的 class

---

## 输出要求

每个模块的 demo 必须：
1. 是独立的 HTML 文件，包含完整的 token CSS + shell（sidebar + header + substrip）
2. 支持 dark / light 主题切换
3. 使用真实的业务数据（条码、文件名、日期等）
4. 所有交互状态都要展示（空状态 / 数据加载 / 正常 / 异常）
