# 正式 IMAP 只读盘点验证记录

## 运行范围

- 运行日期：2026-09-18；历史快照捕获时间为 `2026-09-18T16:06:53.470889+08:00`。
- 邮箱标识：`imap-shadow-20260918`；实际 Inbox 与 Sent 路径已在忽略的 `.env` 中配置，本文不记录路径或凭据。
- 业务库：`email_agent_imap_shadow_20260918`；测试库：`email_agent_imap_shadow_20260918_test`。两者均为本主题新建隔离数据库。
- Embedding 身份：`Snowflake/snowflake-arctic-embed-m-v1.5`，revision `e58a8f756156a1293d763f17e3aae643474e9b8a`，768 维，index version `dev-snowflake-m-v1.5-001`。
- 生成模型：`deepseek-v4-flash`。本阶段不将其调用结果作为质量或时延指标。

## 阶段 1：依赖与只读边界

- `docker compose --env-file .env -f deploy/mvp/compose.yaml config --quiet` 通过。
- Embedding `/info`、生成服务 `/models`、IMAP 登录及 Inbox/Sent 的只读 `SELECT` 均通过。
- 镜像构建、`alembic upgrade head` 和 API `/health` 均通过；启动前该邮箱标识的历史任务数为 0。
- 未发现 SMTP 实现或 Compose 配置；停止前模拟发件箱记录数为 0。

## 阶段 2：历史初始化结果

| 指标 | 结果 | 口径 |
| --- | ---: | --- |
| 已读取源邮件 | 243 | Inbox 154 + Sent 89；不是客户来信数 |
| 确定收发配对 | 12 | 仅头部可确认的一对一关系 |
| 待审核候选 | 12 | 尚未人工确认、审核或发布 |
| 未支持关联 | 219 | 见下表 |
| 已投影业务邮件 | 32 | 明确未配对历史 Inbox 邮件的后续工作流结果 |
| 待人工审核草稿 | 29 | 仅为模拟流程状态 |
| 已归档业务邮件 | 3 | 仅为模拟流程状态 |
| 已发布候选 / 产品文档 | 0 / 0 | 本次未进行人工审核或产品文档导入 |

| 未支持原因 | 数量 |
| --- | ---: |
| `unmatched` | 35 |
| `invalid_message` | 160 |
| `missing_reference` | 5 |
| `missing_message_id` | 1 |
| `complex_relationship` | 9 |
| `duplicate_message_id` | 9 |

## 覆盖范围限制

同一只读账户的 IMAP `STATUS` 返回 Inbox 2,531 封、Sent 1,299 封；但本次运行所用的 `UID SEARCH ALL` 分别仅返回 Inbox 154 个 UID（2383–2540）和 Sent 89 个 UID（1211–1299）。历史任务与独立 UID 搜索复核一致，因此本记录只能证明 243 个 UID 搜索可见源邮件已经处理，**不能表述为 3,830 封状态计数的正式全量盘点**。在解释差异前，不应据此推断全邮箱邮件总量或比例。

## 候选主题归纳（非人工分类）

12 个待审核候选的主题主要涉及：LincOS/固件下载与更新、E1 服务管理和 Docker 能力、设备启动界面与连接、S1 系统重建与数据迁移、N2 NVMe 稳定性、风扇与触控笔等配件。所有候选的 `category` 均为空；上述仅为依据脱敏候选主题的归纳，不是人工审核后的分类统计，也未进入知识库。

## 安全停止

已按计划停止 API 与 worker，隔离数据库保留用于审计和后续复查。未运行 SMTP，未向源邮箱写入，未创建模拟发件记录。本轮不是上线效果、盲测、检索质量评测或端到端时延测量。

## 合成邮件扩容

### 阶段 1：公开资料主题目录

- 已新增 `research.md`，记录 E1、S1、N1/N2 的官方支持页、教程页、独立评测和一个网络访问社区反馈来源；内容仅保留 URL、型号、抓取或发布日期、主题摘要和匿名场景。
- 语料中的核心 NAS 支持主题占 65%：系统软件、设备使用、硬件与配件；剩余 35% 仅来自 `research-derived` 的远程访问、客户端兼容性、Unraid 初始配置和磁盘就位主题。

### 阶段 2：本地可重复语料

- 生成脚本：`scripts/seed_synthetic_shadow_mailbox.py`；本次模板哈希（SHA-256）：`858a3dc4f4b41236480edc8ad8c40db61782abcb47f39be3d622534f2f66eaa8`。
- 实际生成命令：`$env:PYTHONPATH=(Resolve-Path ./src).Path; .venv\Scripts\python.exe scripts\seed_synthetic_shadow_mailbox.py --output data\synthetic-shadow-mailbox-20260918`。
- 输出目录为 Git 忽略的 `data/synthetic-shadow-mailbox-20260918`；实测 Inbox 1,346、Sent 711。每个文件带 `X-Synthetic-Source: imap-shadow-augmentation-v1`，使用 `example.invalid` 地址和 `synthetic-*` 标识；目录非空时脚本拒绝覆盖。

### 阶段 3：独立历史任务

- 实际加载命令：`$env:PYTHONPATH=(Resolve-Path ./src).Path; .venv\Scripts\python.exe scripts\seed_synthetic_shadow_mailbox.py --output data\synthetic-shadow-mailbox-20260918 --load-only`。
- Windows 命令行脚本显式使用 Selector 事件循环，以兼容 Psycopg 异步连接；未改动既有 API 或 worker 的默认启动路径。
- synthetic mailbox `imap-shadow-20260918-synthetic-v1` 结果：`scanned_count=2057`、`paired_count=711`、`candidate_count=711`、源记录数 2,057、业务 `emails=0`、模拟 `outbox=0`、未配对原因仅为 635 个刻意无回复的 `unmatched`。
- 真实 mailbox `imap-shadow-20260918` 复核仍为 `scanned_count=243`、`paired_count=12`、`candidate_count=12`、业务邮件 32、模拟发件 0。

### 阶段 4：报告与自动验证

- 报告命令：`$env:PYTHONPATH=(Resolve-Path ./src).Path; .venv\Scripts\python.exe scripts\report_synthetic_shadow_augmentation.py --format json`。报告只输出两个 mailbox 的聚合计数；仅在压测汇总口径显示 Inbox 1,500、Sent 800、总计 2,300。
- `PYTHONUTF8=1` 下，文件与报告测试 3 项通过：`test_synthetic_mailbox_has_exact_counts_and_stable_headers`、`test_synthetic_mailbox_refuses_nonempty_output_without_clean_option`、`test_summary_markdown_contains_counts_but_no_mail_content`。
- `PYTHONUTF8=1` 下，独立历史加载测试 `test_synthetic_history_load_is_isolated_from_business_email_flow` 通过，验证 2,057/711/711 和 0 条业务邮件、0 条模拟发件。
- 本次没有连接 IMAP、SMTP、生成服务或 Embedding 服务；合成主题不代表真实邮件比例、真实故障率或上线吞吐量，也没有进行人工审核、性能压测或端到端回复质量评估。

## 阶段 3 限定执行：官方产品文档与知识库导入

- 本次范围仅包含官网支持资料摘要和知识库导入；未审核或发布真实邮件候选，未执行检索召回、草稿生成、人工审核或模拟发件。
- 已在 Git 忽略的 `data/knowledge` 创建三份 UTF-8 Markdown：E1/LincOS 支持入口、N1/N2/S1 的 Unraid 与硬件支持、全型号选择与使用场景。每份只保留官方来源 URL、适用范围、能力摘要和安全处理边界，不复制长文或客户内容。
- 实际导入命令：`$env:PYTHONUTF8='1'; $env:PYTHONPATH=(Resolve-Path ./src).Path; .venv\Scripts\python.exe scripts\import_product_knowledge.py`。
- 导入结果：3 份 `product_doc` 均为 active、版本 1；每份生成 4 个知识片段，共 12 个。重复执行复用同一版本，未产生新版本。
- 导入调用现有 `KnowledgeService` 与本地 Embedding 服务；未构造 IMAP 适配器，未运行 SMTP、生成模型、worker 或 API。
- 回归验证：`tests/integration/test_knowledge_publish.py -k product_import_keeps_blockquote` 通过（1 passed，22 deselected）；`git diff --check` 通过。

## 检索评估运行（未完成质量标注）

- 产品资料冻结命令：`$env:PYTHONPATH=(Resolve-Path ./src).Path; .venv\Scripts\python.exe scripts\freeze_product_knowledge.py --freeze-id product-support-v1`；结果为 8 份 active `product_doc`、22 个片段、冻结 SHA-256 `fe66be2cf466fc731a0430fb14f6a6aaa9261bc6cd9ceadf0790ca3e9280ed9e`。
- 评估迁移：`.venv\Scripts\python.exe -m alembic upgrade head` 后 `alembic current` 为 `0008_evaluation_runs (head)`。
- v2 生成与投影命令：`.venv\Scripts\python.exe scripts\seed_synthetic_shadow_mailbox_v2.py --output data/synthetic-shadow-mailbox-20260918-v2 --load-and-project`；只使用本地 Mock 邮箱，实际统计为 2,057 源邮件、711 配对、635 业务邮件和 0 模拟发件。
- 检索命令：`.venv\Scripts\python.exe scripts\run_retrieval_evaluation.py --freeze-id product-support-v1 --evaluation-run-id retrieval-v1`；运行冻结 540 个样本并写入 3,702 条检索观察，查询改写次数为 0。
- 盲化输入命令：`.venv\Scripts\python.exe scripts\export_codex_judge_inputs.py --evaluation-run-id retrieval-v1`；生成 1,620 条本地受控判定输入，映射 SHA-256 为 `ecd3cdeda4f548b3b5823cb4e236388d5bce82e15c1e14f26766043620f15d1c`。
- 限制：没有导入 Codex 初标、人工抽检或人工最终 `Review`。本次没有有效 Recall、MRR、草稿 P95、审核率或真实客户效果结论；未调用 IMAP、SMTP、自动批准或模拟发件。
- 阶段 5 工具验证：`tests/integration/test_codex_judgment_import.py`、`tests/unit/test_retrieval_judgment_metrics.py` 与 `tests/integration/test_evaluation_reports.py` 通过。实际运行 `report_retrieval_evaluation.py --evaluation-run-id retrieval-v1 --format markdown` 只输出来源拆分的观察数、成功/空结果/失败和 P50/P95；因初标与抽检为空，明确输出“质量指标未输出”。
- judge 固定重跑：`retrieval-judge-v2` 使用 `judge_model=codex`、`judge_prompt_version=retrieval-judge-v1`、`judge_run_id=retrieval-judge-v2`；读核对显示三个通道均覆盖 540 个样本、共 4,128 条候选或空结果观察。盲化导出生成 1,620 条输入，映射 SHA-256 为 `7de1dd47911311bfa37c313eb07455a035c6574c9200636f7da731e61333e663`。未导入标签，故仍无质量指标。
- Codex 初标：受控输入经语义匹配规则产生 4,128 条候选标签，并以 `import_codex_judgments.py` 完整导入 `retrieval-judge-v2`；导入器校验了映射哈希、每个候选恰好一次覆盖和固定 judge 身份。`export_retrieval_audit_sample.py` 实际导出 1,488 条人工抽检项。人工抽检尚未导入，报告继续只输出非质量指标。
