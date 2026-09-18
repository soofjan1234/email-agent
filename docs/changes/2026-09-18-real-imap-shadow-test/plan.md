# 正式 IMAP 只读盘点与模拟处理计划

## 前提和执行原则

本计划直接读取正式邮箱中配置的 Inbox 与 Sent 文件夹，不创建专用测试文件夹，也不按日期拆分历史邮件。所有命令在仓库根目录执行。计划不修改业务源码、不接 SMTP，也不允许 Agent 向源邮箱写入任何内容。

每个阶段的实际命令、时间窗、匿名邮箱标识、样本数、模型/知识库版本和结果写入本主题后续创建的 validation.md；在该文件出现真实结果前，不得称为已完成。

## 阶段 1：隔离依赖并证明正式邮箱只读边界

**依赖**：已取得正式邮箱的只读 IMAP 凭据，并已确认 Inbox 与 Sent 的实际 IMAP 路径。

**修改文件**：仅修改被 Git 忽略的 .env；不改任何业务源码或已跟踪配置文件。

**配置要求**：

~~~env
MAILBOX_ID=imap-shadow-20260918
MAILBOX_ADAPTER=imap
IMAP_HOST=<真实主机>
IMAP_PORT=993
IMAP_USE_SSL=true
IMAP_USERNAME=<只读账号>
IMAP_PASSWORD=<只读密码或应用专用密码>
IMAP_MAILBOX_FOLDER=INBOX
IMAP_SENT_FOLDER=<正式邮箱实际 Sent 路径>
GENERATOR_BASE_URL=<真实生成服务>
GENERATOR_API_KEY=<真实生成服务密钥>
GENERATOR_MODEL=<真实生成模型>
~~~

DATABASE_URL 与 MVP_DATABASE_URL 必须指向新建的隔离业务库；TEST_DATABASE_URL 与 MVP_TEST_DATABASE_URL 指向名称以 _test 结尾的不同隔离测试库。不得复用现有 email_agent、email_agent_snowflake_test 或任何已有测试主题的数据库。

**失败门槛**：以下任一项失败即停止，不启动 worker：配置校验失败、数据库名复用、IMAP Inbox/Sent 路径不可只读选择、生成服务或 Embedding 服务不可达。

~~~powershell
docker compose --env-file .env -f deploy/mvp/compose.yaml config --quiet
docker compose -f deploy/embedding/compose.yaml up -d
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18080/info
docker compose --env-file .env -f deploy/mvp/compose.yaml build api
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api alembic upgrade head
docker compose --env-file .env -f deploy/mvp/compose.yaml up -d api worker
Invoke-RestMethod http://127.0.0.1:8000/health
~~~

**通过条件**：配置、迁移和 /health 成功；当前邮箱标识在隔离数据库中尚未有历史任务；没有 SMTP 连接、真实发信或源邮箱写入。

## 阶段 2：盘点全部历史邮件并形成审核候选

**依赖**：阶段 1 通过。

**关联组件**：src/worker.py 的 run_once、src/services/mail_sync.py 的 run_history 和 project_unmatched_history、src/api/cases.py 的配对/候选审核接口、src/api/knowledge.py 的产品文档导入接口。

**执行步骤**：

1. 等待 worker 完成正式 Inbox 与 Sent 的全量历史初始化；只读查询并记录 scanned_count、paired_count、candidate_count、unsupported_count、原因与 initialization_boundary。
2. 查询确定配对和候选。scanned_count 是两个文件夹读取的源邮件总数，不将其表述为客户来信数。
3. 对每个确定配对执行人工确认；对需要纳入知识库的候选补全事实来源、适用条件、回复模板、风险标签和售后问题分类后审核发布。复杂关联、未配对、解析失败和未发布候选保留原因，不进入知识库。
4. 汇总人工已分类候选，输出主要售后问题、各类数量、分类分母、未分类和未审核数量；同时记录 active 候选、产品文档数量和完整 Embedding 身份。

~~~powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/mail-sync-jobs?mode=historical_backfill'
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/case-pairs?status=paired'
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/case-candidates?status=candidate'
~~~

配对确认请求为 POST /api/v1/case-pairs/{pair_id}/confirm，正文只包含 action: confirm 与审核人。候选审核为 POST /api/v1/case-candidates/{candidate_id}/review，必须使用候选返回的当前 revision；审核通过后以返回的新 revision 调用 POST /api/v1/case-candidates/{candidate_id}/publish。产品文档导入使用 POST /api/v1/knowledge/import，路径必须位于 KNOWLEDGE_ROOT。

**通过条件**：历史任务为 succeeded；报告能回答源邮件读取量、确定配对数、未配对/不支持原因，以及基于人工分类分母的主要售后问题；真实网络发信次数为零。

## 阶段 3：可选的产品文档知识库导入

**范围**：本阶段仅将官网支持资料整理为受控本地 Markdown 并导入产品知识库。阶段 2 的 12 个真实邮件候选保持 `candidate` 状态，不执行配对确认、候选审核或发布，也不将其作为检索来源；本阶段不验证草稿、模拟发件或真实网络发信。

**新增文件**：`KNOWLEDGE_ROOT/lincstation-official/*.md`；**复用文件**：`src/api/knowledge.py` 的 `POST /api/v1/knowledge/import`、`src/services/knowledge.py` 的 `KnowledgeService.import_document`。

**执行步骤**：

1. 仅依据官网支持页、下载页和型号手册编写 UTF-8 Markdown；每份文档在首段记录官网 URL、产品型号、文档版本或抓取日期。不得包含真实邮件、客户身份、论坛评论正文或未经来源支持的故障率结论。
2. 将文档保存到运行配置限定的 `KNOWLEDGE_ROOT/lincstation-official/`。导入请求只提交相对路径、标题、适用型号、系统版本和分类；不接受 HTTP 指定的本机绝对路径。
3. 在显式开启 `KNOWLEDGE_LOCAL_IMPORT_ENABLED` 的隔离环境中调用导入接口；导入成功后记录返回的产品文档标识、内容指纹、模型身份和片段数。

~~~powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/knowledge/import -ContentType 'application/json' -Body '{"path":"lincstation-official/e1-lincos-support.md","title":"LincStation E1 LincOS 支持摘要","product_model":"E1","category":"official-support"}'
~~~

**通过条件**：每份导入文档的路径都位于 `KNOWLEDGE_ROOT`、来源与型号可追溯，导入响应为已发布产品文档；12 个真实候选仍全部保持未审核、未发布，真实网络发信次数为零。

## 阶段 4：记录证据并安全停止

**依赖**：阶段 1、2 已记录结果或明确停止原因。

**修改文件**：首次实际运行后创建 docs/changes/2026-09-18-real-imap-shadow-test/validation.md，更新本主题 status.md 的计划结果与下一步；不改写 MVP 历史验证记录。

**执行步骤**：在 validation.md 写入正式邮箱全量盘点范围、IMAP 路径的匿名标识、源邮件读取量、配对和候选统计、人工分类汇总、模型/知识库身份、异常和未测指标。停止 API/worker，保留隔离数据库以便审计和重复检查。

~~~powershell
docker compose --env-file .env -f deploy/mvp/compose.yaml stop api worker
~~~

**通过条件**：报告没有将历史回放描述为上线效果、盲测或严格端到端 P95；真实网络发信次数为零。

## 后续子计划：合成规模扩容

已确认在保留真实 IMAP 基线 Inbox 154、Sent 89 的前提下，增加可追溯合成来源，使压测汇总达到 Inbox 1,500、Sent 800。实施、隔离边界和验证命令见 [合成邮件扩容子计划](plans/2026-09-18-synthetic-mail-augmentation.md)；该子计划不读取 IMAP，也不将合成结果表述为真实邮件盘点。

## 后续子计划：检索、草稿与审核评估

在官方资料集补齐并冻结后，保留 synthetic v1 审计基线，创建独立 synthetic v2 的 127 封垃圾邮件和 508 封待回复邮件，评估检索、草稿、Codex 初标、人工抽检和审核结果。实施顺序、隔离边界、失败门槛和验证命令见[检索、草稿与审核评估子计划](plans/2026-09-18-retrieval-draft-review-evaluation.md)；该子计划不读取更多 IMAP 邮件，不真实发信，也不将 synthetic 结果表述为真实客户结论。
