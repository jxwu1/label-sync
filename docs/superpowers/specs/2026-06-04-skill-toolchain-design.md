# 固定 skill 工具链 + 三层工作流设计

**日期：** 2026-06-04
**状态：** 已批准（待执行）
**作者：** jxwu1 + Claude（brainstorming）

---

## 1. 背景与痛点

ECC 插件往 context 平铺几百个 skill，绝大多数（rust / healthcare / blockchain / 移动端 / 各类垂直行业）从未用过，是噪音税。目标是**一次性设计好一套经过验证、流程化的工具链，固定下来不再反复折腾**。

真正的核心痛点（最终澄清）：

> **常开 auto mode，怕它无人看管时瞎搞。需要一套经过验证的护栏流程让 auto 模式不跑偏。token 不计成本。**

关键认知：**skill 是"建议"，auto mode 下模型可以跳过；hook 是"强制"，确定性拦截，绕不过。** 防瞎搞的硬保证靠 hook，流程套路靠 skill。

## 2. 范围与冻结边界

- **全局固定核心** = 通用全栈 + 预测/数据。装在 `~/.claude`，跟随所有项目。
- **项目专用 skill** 以后按项目单独叠加，不进固定核心。
- 本设计只定义**全局固定核心**，冻结后不再动。

## 3. 三层架构

```
工具箱 = 3 层（review 外包给 Codex，不在 Claude skill 内）
  ① 工作流层 —— Claude 按什么阶段走
  ② 护栏层   —— auto mode 跑偏时 hook 硬拦
  ③ 领域工具层 —— 论文 / 预测 / 搜索
```

### 层 ① 工作流脊柱

Addy 的 7 个 slash 命令天生阶段化，正好满足"每阶段一个固定动作"；superpowers 退成 worktree/并行的动力插件，补 Addy 的空缺。

| 阶段 | 固定动作 | 来源 |
|---|---|---|
| define/plan | 先写 spec + 步骤计划，**你批准后才放 auto 跑** | Addy `/spec` `/plan` |
| isolate | `using-git-worktrees` 隔离环境 | superpowers |
| build | **TDD**：测试先行 → 实现 → 转绿才算完 | Addy `/build` + `test-driven-development` |
| parallel | `dispatching-parallel-agents` 按需加速 | superpowers |
| test | **pytest + Playwright 实测，必须贴通过证据** | Addy `/test` + `verification-before-completion` |
| review | Claude fresh-subagent 审 → Codex 异视角审 → 修复收敛回 Claude | superpowers `requesting-code-review` + Codex |
| ship | ci-cd + 发布清单 | Addy `/ship` |

**单写者原则（single-writer）**：审查查出 bug 后，**只有 Claude 落笔修改**，Codex 全程是批评家只产出"问题清单"不动文件。理由：风格一致性（Codex 冷启动只看 diff，Claude 全程在 repo 规约上下文里）、上下文连续性、TDD 闭环连贯。修复也走 TDD（先写复现测试）。**label-sync 共享代码库永不让 Codex 落笔。**

### 层 ② 护栏（hook，auto mode 硬拦）

| # | 红线 | 范围 |
|---|---|---|
| ① | **禁止直推/push main** | 拦对 main 的 commit/push，逼走 feat 分支。防 Coolify 监听 main push → auto-redeploy 杀后台进程 |
| ② | **主档破坏性操作二次确认** | 只拦 `rm -rf` / 删真库 / 动 stockpile 主档人工数据；**不拦**日常 alembic/wipe 派生数据 |
| ③ | **迁移强制临时 sqlite** | alembic/迁移验证强制走 `LABEL_SYNC_DB_PATH` 临时库，禁止打共享 PG 真库 |

降级项：**"完成声明前查测试"不做 hook**（语义测不准、会高频误拦变成新 GateGuard），交给 test=B 验证阶段 + `verification-before-completion` skill 覆盖。

补充：**Anthropic Claude Code Setup 插件**（只读推荐引擎）跑一遍会针对本项目推荐更多 hook，届时再增补。

### 层 ③ 领域工具

| 类别 | 取舍 | skill |
|---|---|---|
| 论文 | **无**（正文用户自己写，Claude 只管代码） | — |
| 预测 | 回测严谨 + 领域论证 | `eval-harness` + `mle-workflow` + `inventory-demand-planning` |
| 搜索 | 深度研究 + 速查 + 查文档 | `deep-research` + `exa-search` + `context7` |

内置 `WebSearch`/`WebFetch` 本来就有，上面三个是加结构/加质量。

## 4. 安装 / 保留 / 移除清单

| 动作 | 对象 | 说明 |
|---|---|---|
| 装 | **Addy agent-skills** | `/plugin marketplace add addyosmani/agent-skills` → install。工作流脊柱 |
| 装 | **Anthropic Claude Code Setup** | 只读推荐引擎，跑完补 hook |
| 留 | **superpowers** | worktree / 并行 / TDD / 验证 / brainstorming |
| 留 | **Codex** | 外部异视角审查（已有） |
| 留 | **dailybrief hook** | 个人脚本（`~/scripts`），与 ECC 无关，不动 |
| 卸 | **ECC 插件** | 杀噪音本体 |
| cherry-pick | `html-mirror` + `accessibility` + `eval-harness` + `mle-workflow` + `inventory-demand-planning` | 卸 ECC 前先拷成独立 skill 到 `~/.claude/skills/` |
| 随 ECC 移除 | **GateGuard** | 单人项目摩擦 > 价值；纪律由 doubt/review skill 覆盖 |

## 5. 执行顺序（先加法后减法，可回退）

1. **加法（零风险）**：装 Addy + 装 Anthropic Setup 插件 + cherry-pick ECC 该留的 5 个 skill 到 `~/.claude/skills/`
2. **跑推荐**：在 label-sync 里让 Anthropic Setup 插件 "recommend automations for this project"，拿到 hook/MCP 建议
3. **写 hook**：实现层 ② 三条 hook（+ 插件推荐里值得的）
4. **试运行**：跑两天确认 Addy 脊柱顺手、hook 不误拦
5. **减法（不可逆，前置已备份该留的）**：卸载 ECC 插件
6. 更新 memory：记录冻结的工具链核心

**分工**：`/plugin` 交互命令由用户敲；cherry-pick / 写 hook / 写文档 / 验证由 Claude 做。

## 6. 这套如何回答核心痛点

auto mode 跑的是**你批过的计划**（define 闸）→ 行为被**测试钉死**（TDD）→ 完成要**贴证据**（test 闸）→ 合并前**三层独立眼睛**（fresh subagent → Codex → 你）→ **三条硬红线 hook 绕不过**。token 不计成本处（deep-research / 并行 agent / 双重审查）全开。
