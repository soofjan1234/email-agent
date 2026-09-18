# 合成邮件扩容子计划

## 目标与固定口径

保留既有正式 IMAP 只读盘点结果，不再读取 IMAP。以独立的合成邮箱来源补齐测试规模，报告中始终分开保存真实基线和合成数据。

| 来源 | Inbox | Sent | 合计 |
| --- | ---: | ---: | ---: |
| 已有 IMAP 基线 | 154 | 89 | 243 |
| 新增合成数据 | 1,346 | 711 | 2,057 |
| 汇总压测口径 | 1,500 | 800 | 2,300 |

合成来源不代表真实客户邮件、真实问题分布或生产吞吐量。真实售后问题结论仍只使用既有 243 个 IMAP UID 搜索可见源邮件。

## 前置条件

- 既有隔离业务库 `email_agent_imap_shadow_20260918` 保留且不清空；已有历史任务、候选和审计记录不得修改。
- 不启动 IMAP 适配器，不调用 SMTP、生成服务或 Embedding 服务。
- 合成邮箱标识固定为 `imap-shadow-20260918-synthetic-v1`，仅用于本子计划；不得复用真实 IMAP 的 `MAILBOX_ID`。
- 合成邮件只能使用 `example.invalid` 地址、`synthetic-*` Message-ID、固定时间窗和模板化内容；不得复制客户姓名、地址、正文、订单号或设备序列号。

## 阶段 1：调研产品功能与公开问题素材

**新增文件**：`docs/changes/2026-09-18-real-imap-shadow-test/research.md`。

1. 访问 [LincPlus 支持页](https://www.lincplustech.com/support.html)、[官方下载页](https://www.lincplustech.com/download.html) 及各型号支持资料，记录可验证的产品功能、安装/升级/恢复入口和文档版本。
2. 检索公开独立评测和用户反馈，至少覆盖 LincStation E1、S1、N1/N2；对每条外部材料记录 URL、发布日期或抓取日期、产品型号、观察到的问题主题与来源类型（官方或独立反馈）。
3. 将来源归纳为不含客户原文的合成主题目录。核心 NAS 支持目录固定为系统软件、设备使用、硬件与配件；阶段 1 调研发现的其他主题单列为 `research-derived`。每个主题至少保留一个来源链接和“可生成的匿名问题场景”。
4. `research.md` 必须明确：官方资料说明产品能力或支持路径；独立评测/用户反馈只用于设计合成问题，不能代表故障率、真实用户占比或官方承诺。不得复制长段落、评论正文或个人信息。

**验证命令**：

```powershell
rg -n "来源|产品型号|功能|问题主题|匿名问题场景|限制" docs/changes/2026-09-18-real-imap-shadow-test/research.md
```

**通过条件**：三类核心 NAS 支持主题均有可生成的匿名场景；每个 `research-derived` 主题均有可追溯来源，否则不纳入语料；研究记录不含客户邮件、个人信息、无来源断言或超过合理摘录范围的原文。

## 阶段 2：生成可追溯的 `.eml` 语料

**新增文件**：`scripts/seed_synthetic_shadow_mailbox.py`、`tests/integration/test_synthetic_shadow_augmentation.py`。

1. 先在测试中声明目标：生成 1,346 个 `inbox` 文件、711 个 `sent` 文件；文件名、`Message-ID`、日期和正文内容在重复执行时保持完全一致。
2. 生成 711 组一对一收发邮件：每个 Sent 使用对应 Inbox 的 `Message-ID` 写入 `In-Reply-To` 和 `References`。另外生成 635 个没有 Sent 的 Inbox 邮件。
3. 为每个文件写入 `X-Synthetic-Source: imap-shadow-augmentation-v1`，并使用 `synthetic/` 前缀的文件名。此标记与独立 mailbox ID 共同构成审计链路。
4. 将语料写到 Git 忽略的 `data/synthetic-shadow-mailbox-20260918/{inbox,sent}`；脚本拒绝覆盖非空目录，除非调用方显式提供本子计划规定的清理参数。

**内容配额**：711 个已回复案例中，核心 NAS 支持主题固定为 462（65%）：系统软件 185（下载、升级、服务管理、Docker 功能）、设备使用 160（开机界面、网络连接、系统重建、数据迁移）、硬件与配件 117（硬盘稳定性、风扇噪音、触控笔配件）。其余 249（35%）仅使用阶段 1 的 `research.md` 中具有来源的 `research-derived` 主题。635 个无回复来信沿用相同 65/35 比例：核心 NAS 支持 413、调研衍生主题 222；两类均不创建 Sent。

**验证命令**：

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
.venv/Scripts/python.exe -m pytest tests/integration/test_synthetic_shadow_augmentation.py -q
.venv/Scripts/python.exe scripts/seed_synthetic_shadow_mailbox.py --output data/synthetic-shadow-mailbox-20260918
```

**通过条件**：文件数严格为 Inbox 1,346、Sent 711；每个合成 Sent 均可回溯到一个合成 Inbox；没有非 `example.invalid` 地址或非 `synthetic-*` 标识。

## 阶段 3：写入独立 synthetic mailbox 历史任务

**修改文件**：`scripts/seed_synthetic_shadow_mailbox.py`；**复用文件**：`src/adapters/mailbox.py` 的 `MockMailboxAdapter`、`src/services/mail_sync.py` 的 `MailSyncService.run_history`。

1. 脚本仅对 `imap-shadow-20260918-synthetic-v1` 构造运行时配置，并通过 `MockMailboxAdapter` 读取阶段 2 的本地 `.eml`。禁止实例化 `IMAPMailboxAdapter`。
2. 脚本只调用 `run_history`，不调用 `project_unmatched_history`、`run_next_incremental` 或 `WorkflowDispatcher`，避免把合成邮件送入生成、检索或模拟发送链路。
3. 成功后读取 synthetic mailbox 对应的历史任务、配对和候选计数；真实 `imap-shadow-20260918` 的历史任务和 243 条源记录必须保持原样。

**验证命令**：

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
.venv/Scripts/python.exe scripts/seed_synthetic_shadow_mailbox.py --output data/synthetic-shadow-mailbox-20260918 --load-only
```

**通过条件**：synthetic 历史任务为 `succeeded`，`scanned_count=2057`、`paired_count=711`、`candidate_count=711`；真实历史任务仍为 `scanned_count=243`；不存在 synthetic mailbox 的 `emails`、`outbox` 或 SMTP 发送记录。

## 阶段 4：汇总与证据记录

**新增文件**：`scripts/report_synthetic_shadow_augmentation.py`；**修改文件**：`docs/changes/2026-09-18-real-imap-shadow-test/validation.md`、`docs/changes/2026-09-18-real-imap-shadow-test/status.md`。

1. 报告脚本分别查询真实和 synthetic mailbox 的源邮件、配对、候选及未支持原因，输出结构化 JSON 与脱敏 Markdown 汇总。
2. 报告只在“压测汇总口径”栏显示 Inbox 1,500、Sent 800、合计 2,300；真实邮件数量和问题结论单独保留 243 的来源边界。
3. 更新 `validation.md`，登记脚本版本、模板哈希、实际命令、两类数据的独立指标和未测项；更新 `status.md` 的子计划状态。

**验证命令**：

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
.venv/Scripts/python.exe scripts/report_synthetic_shadow_augmentation.py --format json
git diff --check
```

**通过条件**：报告的真实基线、合成增量和汇总口径可独立复算；不含邮件正文、地址、凭据或客户身份信息；`git diff --check` 通过。

## 风险与停止条件

- 若输出目录已有未知文件、目标 mailbox 已有历史任务、合成 Message-ID/配对关系不完整，脚本必须停止，不覆盖或追加。
- 若阶段 1 的来源无法验证或主题目录缺失，停止阶段 2；不得以未经记录的网页内容填充合成语料。
- 若任何步骤尝试连接 IMAP、SMTP、生成服务或 Embedding 服务，立即停止，并将该次运行标记为失败。
- 若真实 mailbox 的统计在合成加载后发生变化，停止后续步骤并保留数据库供审计。
