# NAS 售后邮件回复 Agent：技术选型

## 1. 选型目标

技术选型服务于当前 MVP：快速验证 NAS 售后邮件的检索、回复生成、人工审核和知识积累闭环。当前没有高吞吐或超大规模向量检索证据，因此优先降低 AI 能力集成、效果实验和本地部署成本，不为未来规模提前引入分布式组件。

## 2. 选型结论

| 领域 | 选择 | 当前结论 |
| --- | --- | --- |
| 后端语言 | Python | 已确定 |
| Web 框架 | FastAPI + Pydantic | 已确定 |
| 前端 | Vue 3 + TypeScript + Vite | 已确定 |
| 数据库 | PostgreSQL | 已确定 |
| 向量存储 | pgvector | 已确定 |
| 数据访问 | SQLAlchemy 异步模式 + psycopg + Alembic | 已确定 |
| 模型 HTTP 客户端 | httpx 异步客户端 | 已确定 |
| 后台任务 | 非 Agent 任务使用 PostgreSQL 任务表；Agent 由 LangGraph 运行 | 已确定 |
| Agent 编排 | LangGraph + PostgreSQL Checkpointer | 已确定 |
| 英文关键词检索 | PostgreSQL `english` `tsvector` + GIN，并保留 NAS 标识 | 已确定，标识保留效果需验证 |
| 向量检索 | pgvector 精确余弦检索 | MVP 已确定 |
| 结果融合 | 倒数排名融合（RRF） | MVP 默认基线，效果对比与调参放到第二版 |
| 重排模型 | MVP 不使用 | 检索评测不达标时再引入 |
| 大语言模型 | `gpt-4o-mini`，JSON Schema 模式 | 已按英文 JSON / 引用 / 安全 truth test 冻结 |
| Embedding 模型 | Docker 部署开放模型；当前英文 CPU 优先候选为 Snowflake Arctic M v1.5（768 维） | 四模型本地扩展集三轮对比已完成，生产模型尚未冻结；原 API key 网关选型已废弃 |
| Python 测试 | pytest + pytest-asyncio | 已确定 |
| 前端测试 | Vitest + Vue Test Utils | 已确定 |
| 端到端测试 | Playwright，仅覆盖关键审核闭环 | 已确定 |
| 本地部署 | Docker Compose | 已确定 |

## 3. Python

项目主要耗时来自模型网关、Embedding、PostgreSQL 和文件处理等外部 I/O，当前没有 CPU 密集或高吞吐证据。Python 能降低模型接入、文本清洗、分词、RAG 实验和离线评测成本，更适合当前阶段。

选择边界：

- 不声称 Python 能满足未经测量的未来吞吐，只确认它适合当前 MVP。
- 邮件解析、清洗和检索不能在异步事件循环中执行长时间 CPU 计算；出现实测瓶颈后再移到线程池、进程池或独立服务。
- Python 版本使用项目创建时仍受核心依赖支持的稳定版本，并在 `pyproject.toml` 和锁文件中冻结，不使用未验证的新版本。

暂不选择 Go 的原因：第一版不连接真实邮箱，没有高并发常驻同步压力，核心工作是 AI 效果迭代。第二版也不会默认拆出 Go 服务，只有并发、资源或部署证据证明有必要时才重新评估。

## 4. FastAPI 与 Pydantic

FastAPI 基于 ASGI，适合模型 HTTP 调用和异步数据库访问等 I/O 场景。Pydantic 用于统一校验 API 请求、响应和 Agent 结构化输出，并生成开发期接口文档。

异步成立的前提：

- 模型调用使用 `httpx.AsyncClient`；
- PostgreSQL 使用 SQLAlchemy 异步会话和 psycopg 异步驱动；
- 文件解析或不支持异步的库不伪装成异步调用；
- 完整 Agent 流程不在 HTTP 请求内执行，由独立进程调用 LangGraph 异步处理；
- HTTP 接口负责创建任务、人工操作和查询状态。

没有选择 Flask：Flask 可以编写异步视图，但 WSGI 模型下每个请求仍占用一个 worker；本项目还需要较多结构化契约，FastAPI 的默认组合更直接。

没有选择 Django：Django 的 ORM 和 Admin 成熟，但项目已经使用 Vue 构建审核与知识管理页面，Django Admin 会形成第二套交互体系；当前不需要其完整应用框架。

## 5. PostgreSQL 与 pgvector

PostgreSQL 同时承载：

- 邮件、审核、候选案例和审计等业务数据；
- LangGraph checkpoint、interrupt 和恢复所需的运行状态；
- 使用 `tsvector` 和 GIN 的关键词检索；
- 使用 pgvector 的向量语义检索。

选择 pgvector 的原因：业务数据本就需要 PostgreSQL，将向量存入同一数据库可以减少独立向量数据库、跨库同步和一致性处理。MVP 知识规模较小，先使用精确最近邻检索建立召回基线，不启用 HNSW 或 IVFFlat。

不采用“向量达到固定数量就迁移 Milvus”的规则。只有出现以下测量结果时才重新选型：

- 精确检索或 HNSW 调优后仍无法满足检索 P95；
- 召回率无法达到固定评测集要求；
- 向量查询显著影响业务事务；
- 索引构建、更新或备份时间不可接受；
- 需要向量服务独立扩缩容或高可用；
- 团队能够承担第二套数据系统和同步一致性。

## 6. 英文混合检索

### 6.1 关键词检索

第一版面向海外英文邮件，使用 PostgreSQL `english` 文本检索配置生成 `tsvector`，不再引入中文分词库。

规范化规则：

- 自然语言走 `english` 配置的词干和停用词；
- 单独提取并保留 NAS 型号、错误码、版本号、命令、协议名和缩写；
- NAS 领域词维护在项目词典中；
- 原文始终保留，规范化结果只用于检索；
- 使用固定英文查询集验证规范化是否破坏 `RAID5`、`S.M.A.R.T.`、`SMB`、错误码等关键标识。

### 6.2 向量检索

- 使用 `Embedder` 接口生成查询与知识片段向量；
- MVP 使用 pgvector 精确余弦检索；
- 产品文档和已审核案例分别召回，避免回复样板挤占事实依据；
- 产品型号和系统版本只有在邮件明确给出时才能作为过滤条件。

### 6.3 融合与重排

- 关键词检索与向量检索使用 RRF 融合；
- 产品文档和历史案例各自最多保留 3 条，总候选最多 6 条；
- MVP 使用保守默认的 RRF 常量、召回数量和相关性门槛，第二版再通过固定评测集对比调优；
- MVP 不增加重排模型，只有 Recall@K 尚可但前几名排序持续不达标时才测试重排。

已实现的 A4 固定每个来源（`product_doc`、`approved_case`）独立执行全文和精确余弦向量召回，各通道最多取 20 个候选，再按 `RRF=60` 对同一片段去重融合，每个来源最多返回 3 条。返回片段 ID、文档 ID、来源版本、内容、适用元数据、融合得分和两路名次，供后续引用校验。全文规范化复用已验证的标识保护规则；自然语言词逐个组成 OR 查询，避免未出现在文档中的补充词把候选整体过滤掉。检索不判断 `knowledge_status`，候选存在也不代表依据充分。

## 7. 模型接入

### 7.1 接口边界

定义两个应用接口：

- `Embedder.embed(texts)`：批量返回固定维度向量；
- `Generator.generate(messages, response_schema)`：按指定 JSON Schema 返回 Agent 结果。

基础设施层通过 HTTP 适配器隔离模型运行方式。生成式 LLM 继续使用 OpenAI-compatible 网关；Embedding 使用 Docker 中的开放模型服务，模型专用输入处理由适配器负责，需显式区分查询和文档。上面的 `embed(texts)` 是原接口，评测适配器已扩展为 `embed_queries(texts)` 和 `embed_documents(texts)`。地址、模型、超时及服务需要的可选访问凭据通过配置注入，业务层不依赖具体 SDK。A3 业务适配器复用 TEI 身份与向量校验，通过 `/info` 确认模型、revision 和输入上限，通过 `/tokenize` 对文档前缀及特殊 token 完整计数，单输入调用 `/embed` 并显式设置 `truncate=false`。本地 TEI 不接收生成式网关凭据。

### 7.2 模型选择规则

Embedding 不再按 API key 或网关渠道筛选。按 [Docker 开放模型对比设计](../designs/2026-09-13-embedding-truth-test-design.md) 在相同环境和英文数据集上比较候选，并根据以下指标冻结模型：

- 产品文档与历史案例的 Recall@K；
- NAS 型号、错误码和英文技术标识查询表现；
- 向量维度与数据库占用；
- 单批嵌入延迟、费用和稳定性。

本地已完成 Qwen3 0.6B、Nomic v1.5、Snowflake Arctic M v1.5 和 BGE-M3 的扩展集三轮对比，当前英文短文本、CPU 单输入串行部署优先选择 Snowflake 作为后续候选。选择依据是 Top-3 依据完整覆盖、请求延迟和采样内存的综合表现；它并非所有排名指标都最优。数据为未经独立人工复核的合成集，具体指标、统一部署条件及 Qwen 批次缺陷规避见[完整结果报告](../../../evals/embedding-v2/RESULTS.md)。

大语言模型至少验证：严格 JSON 输出成功率、引用约束、知识不足时拒绝确定性回答、高风险操作拦截和英文回复质量。

原 `text-embedding-3-small`（1536 / `embedding-v1`）冻结文件保留为历史证据，不再作为新部署的建库依据。已获得[本地扩展集比较结果](../../../evals/embedding-v2/RESULTS.md)，生产模型尚未冻结；完成独立标注复核与目标环境验证后再创建新冻结记录和索引版本；已有数据须全量重嵌入后切换，不同模型或输入配置不能在同一向量列混用。

## 8. Python 数据层

三者分别负责不同层次：

```text
FastAPI 业务代码
      ↓
SQLAlchemy：组织模型、查询和事务
      ↓
psycopg：建立连接并向 PostgreSQL 发送 SQL

Alembic：在部署或升级时修改数据库表结构
```

- **SQLAlchemy**：数据库访问层，负责 ORM、查询表达、事务和异步会话，让业务代码不必手写全部常规 SQL。
- **psycopg**：PostgreSQL 驱动，负责真正建立连接、发送 SQL 和读取结果。SQLAlchemy 通过它访问 PostgreSQL。
- **Alembic**：数据库迁移工具，负责按版本创建表、增加字段和索引，以及记录数据库结构如何从旧版本升级到新版本；它不参与普通业务请求。

- API 与 worker 分别创建自己的数据库会话；
- Repository 隐藏具体 SQL，但不增加只做转发的通用 Repository 基类；
- 审核业务事实、模拟发件和候选案例写入使用明确事务与唯一约束；Graph 恢复不依赖 `emails.status` 投影；
- pgvector 和全文检索的特殊查询允许使用明确封装的 SQL，不强迫所有能力都经过 ORM 抽象。

连接池大小、查询超时和事务隔离级别根据本地并发测试设定，不在缺少负载证据时写死生产参数。

psycopg 异步连接在原生 Windows 环境需要使用兼容的事件循环。本项目默认通过 Docker/Linux 运行 API 和 worker；如果直接在 Windows 启动，再显式配置 `SelectorEventLoop` 并进行连接测试。

## 9. LangGraph 与后台执行

### 9.1 采用 LangGraph 的理由

普通 LangChain Runnable 足以组织固定的“检索 → 生成”流水线；如果需求只是生成草稿后等待人工确认，两个接口加一张草稿表会更直接，人工等待本身不是采用 LangGraph 的充分理由。

本项目需要展示非线性的高级 RAG 工作流：检索不相关时重写查询并再次检索，证据不足时补充检索或转人工，生成结果不合格时重新生成，超过重试上限后人工兜底。LangGraph 用 Conditional Edges 和有上限的 Cycles 显式表达判断、回退与循环，避免把流程控制分散到多个服务的 `if/else` 和业务状态字段中。

LangGraph 同时提供两项配套能力：

- PostgreSQL Checkpointer 在节点边界保存 Graph 状态；进程重启或运行失败后，可以从最近的持久化状态恢复。尚未成功完成 checkpoint 的节点仍可能重新执行，因此节点内副作用必须幂等。
- 人工审核节点使用 `interrupt()` 暂停，审核接口使用相同 `thread_id` 和 `Command(resume=...)` 提交批准、编辑后批准、拒绝或转人工结果。

LangGraph 是 Agent 工作流运行状态的唯一来源，不再保留 Agent 专用任务表、worker 租约、过程运行表或另一套暂停恢复状态机。LangChain 的模型、Prompt 和 Retriever 等组件仍可在 Graph 节点内部使用。

### 9.2 Graph 路径

```text
START
  → classify_email
  ├→ spam → archive → END
  ├→ vip_complaint → urgent_manual_handling → END
  └→ normal → retrieve_knowledge
                 → assess_evidence
                 ├→ irrelevant → rewrite_query → retrieve_knowledge
                 ├→ insufficient → request_information_draft
                 ├→ high_risk → manual_handling_draft
                 └→ sufficient → solution_draft
                                      → validate_output
                                      ├→ failed → solution_draft
                                      ├→ retry_limit_reached → manual_handling_draft
                                      └→ passed → human_review interrupt
                                                       ├→ rejected → END
                                                       ├→ manual → END
                                                       └→ approved/edited → simulated_send
                                                                                → create_case_candidate
                                                                                → END
```

查询改写和重新生成必须分别记录计数并设置上限；分类和评估的低置信度默认进入人工路径。VIP 身份以业务数据为准，模型只能辅助识别投诉内容。

每封邮件首次处理使用稳定的 Graph `thread_id`，并在 `emails` 中保存其映射。重新处理必须创建新的 workflow generation 或新 `thread_id`，不能误续接已经结束的 checkpoint。

### 9.3 运行边界

MVP 将开源 LangGraph 嵌入 FastAPI 项目，不假定 Checkpointer 会主动发现或调度工作。独立进程提供薄启动入口，负责发现尚未启动 Graph 的新邮件并调用 Graph；它不维护节点状态、步骤快照或第二套 Agent 状态机。同一 `thread_id` 的并发启动必须拒绝或串行化。

邮箱增量同步、历史回溯、产品文档嵌入和案例发布发生在 Agent Graph 之外，仍可使用精简的 PostgreSQL 任务表和独立 worker。若后续采用 Agent Server，再评估由其替换 Agent 启动调度代码；如果实测需要多队列、定时调度或高吞吐，再比较 Celery、Dramatiq 等任务系统。

业务表继续保存邮件、审核、知识、候选案例和模拟发件结果。`emails.status` 仅是最终一致的查询投影，不参与 Graph 路由；审核前必须校验真实 interrupt。投影更新失败时通过 checkpoint 对账修复。

所有外部或业务副作用继续使用数据库幂等键和唯一约束。模拟发件按 `review_id` 唯一，案例候选按来源唯一；未来接入真实发送时需增加 transactional outbox 或下游幂等键。

## 10. 历史邮件配对

MVP 只处理协议头可确定的一对一历史收件与人工回复，不使用模型决定配对关系。完整关联识别与复杂关系排除规则统一见[总体设计 9.1](../design.md#91-历史邮件配对与案例生产)。

全量扫描完成前不生成配对候选，避免把尚未扫描到的其他回复遗漏。一对多、多对一、多对多及不确定关系保留原文和暂不支持原因，第二版再处理；人工审核不能绕过本版范围。模型只能辅助提取问题与适用条件，案例发布仍需人工复核。

第二版再验证模糊配对的 Precision、Recall 和阈值。已有专项评测中的歧义拦截仅是历史验证证据，不代表启动初始化与完整关系判定已实现。

## 11. 模拟邮箱

`MockMailboxAdapter` 保留为历史夹具入口；B1 的 `IMAPMailboxAdapter` 以只读方式扫描真实邮箱，业务接口只登记增量任务，不直接提交邮件正文。

目录结构：

```text
data/mock-mailbox/
├─ inbox/
│  └─ *.eml
└─ sent/
   └─ *.eml
```

选择 `.eml` 是为了保留 `Message-ID`、`In-Reply-To`、`References`、主题、时间和通信双方，确保模拟环境可以验证第二版真实邮箱所需的配对行为。

- `incremental` 根据持久化同步游标扫描新增邮件；
- `historical_backfill` 在首次启动时自动全量扫描固定初始化边界内的收件和已发送邮件；启动恢复、并发限制及增量衔接遵循总体设计 6.2、6.3；
- 外部邮件标识和内容哈希共同防止重复；
- 测试夹具不存放真实客户数据；
- `data/` 保持在 `.gitignore`，可公开的脱敏样例存放在专门的测试夹具目录。

## 12. 前端

使用 Vue 3 + TypeScript + Vite，页面包括：

- 邮件列表与处理状态；
- 邮件详情、引用依据和可编辑回复草稿；
- 最新邮件同步与自动历史初始化任务进度（无历史范围选择）；
- 历史邮件配对确认；
- 候选案例审核、发布和归档；
- 产品文档导入与状态查看；
- 模拟发件箱。

组件库使用 Element Plus，路由使用 Vue Router。MVP 的跨页面状态较少，服务端数据通过轻量 API client 获取，暂不引入 Pinia；出现跨页面共享编辑状态后再评估。

## 13. 测试与评测

### 13.1 后端测试

- pytest：领域规则和应用服务单元测试；
- pytest-asyncio：异步 API、模型和数据库代码；
- FastAPI 测试客户端或 httpx ASGI transport：接口测试；
- 真实 PostgreSQL + pgvector：迁移、事务、全文和向量检索集成测试；
- Fake `MailboxAdapter`、`Embedder` 和 `Generator`：稳定验证失败与边界路径。

SQLite 不能替代 PostgreSQL 集成测试，因为它无法证明 pgvector、GIN、锁语义和 PostgreSQL 事务行为。

### 13.2 前端与端到端测试

- Vitest + Vue Test Utils：审核交互、风险提示和表单校验；
- Playwright：覆盖“同步邮件 → Agent 草稿 → 人工编辑批准 → 模拟发件”的关键闭环；
- 端到端测试使用可控的假模型响应，不依赖实时外部模型稳定性。

### 13.3 RAG 评测

固定、版本化的 NAS 售后样例集至少记录：

- 期望产品文档和历史案例；
- 期望分类、优先级和风险；
- 是否允许生成确定性步骤；
- 必须出现和禁止出现的回复事实。

检索评测使用 Recall@K、MRR 和错误事实引用率；历史配对使用 Precision、Recall 和歧义拦截率；生成评测记录 JSON 合法率、引用支持率、高风险拦截率和人工直接批准／编辑／拒绝比例。

## 14. 部署与配置

本地使用 Docker Compose，包含：

- `api`：FastAPI；
- `worker`：与 API 使用同一镜像、不同启动命令；
- `web`：Vue 构建结果与静态服务；
- `postgres`：启用 pgvector 的备用数据库服务，通过 `bundled-db` profile 显式启动。

2026-09-16 用户指定优先复用本机 PostgreSQL，业务库与测试库独立创建。应用容器通过 Docker Desktop 的 `host.docker.internal` 连接本机数据库，原生调试使用 `localhost`；本地配置与启动命令见[运行说明](../../../deploy/mvp/README.md)。

生成式 LLM 网关仍作为外部依赖。Embedding 使用独立的 Docker/Compose 部署配置进行开放模型评测，实验配置及四模型接入验证已实现，选定模型后再确定生产部署。数据库迁移使用单独的一次性命令执行，不由多个 API/worker 实例并发迁移。

配置原则：

- 普通配置使用环境变量；
- 本地 `.env` 不提交仓库；
- 提供不含密钥的 `.env.example`；
- 模型和数据库凭据不写入日志或审计事件；
- `data/`、本地数据库和模型缓存不提交仓库；
- 依赖通过 `pyproject.toml` 和锁文件固定。

## 15. 分阶段技术验证

第一版不把每个技术点都做成多方案选型实验。除 Embedding 模型外，优先采用成熟、实现简单的推荐方案；实施前只保留能够证明核心链路可行、正确、安全且可恢复的阻断性验证。效果选优和参数调优放到第二版，避免在没有完整业务闭环时提前优化。

### 15.1 第一版阻断性验证

1. Docker 四模型已完成固定英文 NAS 扩展集的三轮本地对比，可按 Snowflake 优先候选推进 MVP。生产模型和维度待独立标注复核与目标环境验证后冻结；目标环境确定后优先验证该候选，表现不达标时再比较其他模型。历史 small 结果仅作参考，新模型冻结前不据旧记录确定新部署的向量列。Embedding 变化会触发全量重嵌入，因此换模型必须新建索引版本。中文召回不作为第一版冻结条件。
2. 验证大语言模型能够返回合法 JSON，引用本次真实检索片段，并在知识不足或高风险时遵守降级和危险操作拦截规则。
3. 对英文关键词规范化做最小冒烟验证，确保 NAS 型号、错误码、协议和命令不会被破坏；第一版不比较多个分词方案。
4. 使用确定性协议头关系的 `.eml` 样例验证历史邮件配对；模糊配对效果调优不阻塞第一版。
5. 使用包含个人信息和设备标识的样例验证基本清洗与脱敏，证明敏感信息不会进入可复用案例。
6. 验证 PostgreSQL Checkpointer 的人工中断、进程重启恢复、同一 thread 并发保护和 checkpoint 保留策略。
7. 验证查询改写、补充检索、生成校验和重试上限不会形成无限循环。
8. 验证重复审核恢复、节点重放、模拟发件和候选案例创建仍保持幂等。

### 15.2 第二版效果对比

- 比较纯向量检索、关键词检索和 RRF 混合检索的 Recall@K、MRR 与错误事实引用率；
- 调整每路召回数量、RRF 常量、两路权重和最低相关性门槛；
- 比较英文规范化方案和 NAS 领域词典；
- 在 RRF 排序仍不达标时评估 Cross-Encoder 重排；
- 比较多个大语言模型和 Embedding 模型的质量、延迟与成本；
- 对模糊历史邮件配对测量 Precision、Recall 和歧义拦截率。

第一版只能冻结已经完成阻断性验证的模型、维度和安全边界。RRF 参数、召回数量等效果参数先使用保守默认值，不把未经比较的结果表述为最优。

总体业务流程见[总体设计](../design.md)，数据实体见[数据库设计](database-design.md)，HTTP 契约见[接口设计](api-design.md)。
