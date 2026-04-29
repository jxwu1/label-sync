# 前端验证清单

> 阶段 2 (Alpine) PR1/PR2 手测清单。每个 PR 在 description 里贴完成状态。

## 通用 (每个 PR 必跑)
- [ ] 浏览器加载首页无 console error
- [ ] 6 个 nav 都能切到对应 page (main/dup/purchase/attendance/history/data_quality)
- [ ] 货号历史页 2 个二级 tab 切换正常 (查询 / 最近改动)

## PR1: refactor/alpine-stores
- [ ] 拖入 .xlsx / .csv → 文件列表显示 → 点 × 删除一项
- [ ] 上传 → /run → 终端日志实时刷新，badge idle→running
- [ ] 处理中 #status 显示 spinner + 文案
- [ ] 完成后 badge=done，下载/复制按钮显示
- [ ] 点"重置"清空全部 UI，badge 回 idle
- [ ] 复制所有型号 (去重) / (含重复) 两个按钮
- [ ] 重复检查 tab 上传 → 结果显示
- [ ] 终端 FAB 计数 = 日志条数；点击开关抽屉
- [ ] 终端"清空"按钮可用
- [ ] 互传 FAB 点击 → 抽屉打开 → 红点消失
- [ ] 互传抽屉拖入文件 → 列表刷新；下载链接可点
- [ ] 文字互传：输入 → Ctrl+Enter 发送 → 列表显示 → 删除
- [ ] 右下角 quickMenu：点击展开 → 子按钮触发对应抽屉 → 点外部关闭

## PR2: refactor/alpine-nav
- [ ] 6 个 nav 项点击都能切到对应 page，active class 正确
- [ ] 页面刷新后默认在 main tab
- [ ] grep 验证 `static/js/` 下无 `window.switchPage` 残留
- [ ] grep 验证 `templates/` 下无 `onclick="switchPage` 残留
