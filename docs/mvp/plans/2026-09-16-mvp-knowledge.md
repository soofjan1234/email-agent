# 阶段 A：历史初始化与知识准备

依据[整体计划](../plan.md)，范围与验收以其上游设计为准。以下路径均为拟实施路径；命令在对应文件与依赖建立后执行。

## A1：建立可运行应用与持久化验证入口

**依赖**：已确认设计；不依赖业务代码。

**文件**：修改 `pyproject.toml`、`.env.example`；创建 `src/main.py`、`src/config.py`、`src/db.py`、`src/models.py`、`src/worker.py`、`alembic.ini`、`migrations/env.py`、`migrations/versions/0001_business.py`、`deploy/mvp/Dockerfile`、`deploy/mvp/compose.yaml`、`requirements.lock`、`tests/conftest.py`、`tests/integration/test_bootstrap.py`、`tests/integration/test_model_identity.py`。

**先写失败测试**：先验证空库迁移后能保存并查询模拟邮件、唯一约束阻止重复；当前无业务包和表，应失败。另验证候选模型维度或身份不匹配时拒绝写入。

**最小实施步骤**：按已定 FastAPI、SQLAlchemy、psycopg、Alembic、LangGraph 与 pgvector 添加并固定兼容依赖，保存依赖解析结果；按总计划的源码搜索路径约定设置 Docker、pytest 和迁移环境，为业务子目录补齐 `__init__.py`，不创建 `src/__init__.py`；Compose 提供 api、worker，默认连接本机 PostgreSQL，确认可连接后执行一次性迁移；postgres 容器只作备用 profile。实现 Repository 所需业务表和审计基础，不用 SQLite 替代。将 Embedding 模型、revision、输入模板、维度和索引版本作为显式配置，接入现有身份检查，向量相关迁移依据本次验证配置生成；不擅自冻结生产模型。测试数据库与业务数据库隔离。

**验证命令**：

```powershell
docker compose --env-file .env -f deploy/mvp/compose.yaml config --quiet
docker compose --env-file .env -f deploy/mvp/compose.yaml build api
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api alembic upgrade head
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api python -m pytest tests/integration/test_bootstrap.py tests/integration/test_model_identity.py -q
```

**通过条件**：从仓库根目录与容器都能导入业务模块，API 和 worker 按统一启动命令正常运行；空库可迁移且重复迁移无副作用，业务读写与唯一约束真实生效，错误模型配置阻止混写；记录依赖版本和数据库扩展身份。

2026-09-16 执行配置按用户要求优先复用本机 PostgreSQL，并创建独立业务库与测试库；运行步骤见[本地说明](../../../deploy/mvp/README.md)。Compose 的 PostgreSQL 仅作为显式 profile 启用的备用服务。

## A2：启动自动导入历史并生成一对一候选

**依赖**：A1。

**文件**：创建 `src/adapters/mailbox.py`、`src/services/mail_sync.py`、`src/services/pairing.py`、`src/repositories/mail.py`、`src/api/mail_sync.py`、`tests/fixtures/mailbox/`、`tests/integration/test_history_init.py`、`tests/unit/test_pairing.py`；修改 `src/main.py`、`src/worker.py`、`src/models.py` 和对应增量迁移。

**先写失败测试**：先构造回复跨分页的一对多、References 多跳、多对一、多对多、无协议头、空邮箱和重复 Message-ID 样例；要求只有完整确定一对一生成候选。现有逐条配对不能证明完整关联，应在新增行为断言处失败。集成测试在保存邮件后、提交进度前终止任务并重启。

**最小实施步骤**：实现稳定初始化边界与持久化扫描进度，启动检查幂等创建/恢复后台任务；同邮箱串行执行。完整扫描后统一识别关系，复杂或不确定关系仅记录原文及原因。复用规范化和脱敏规则生成唯一候选，全部处理完才成功。实现任务列表/详情与增量入口的初始化保护，拒绝时间范围及手动历史模式。初始化期间新增邮件留待后续增量；历史数据不创建 Agent 运行。

**验证命令**：

```powershell
docker compose --env-file .env -f deploy/mvp/compose.yaml build api
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api python -m pytest tests/unit/test_pairing.py tests/integration/test_history_init.py tests/eval/test_pairing.py tests/eval/test_redact.py -q
```

**通过条件**：双 worker、失败重试和重启不漏数据、不重复案例；跨批次复杂关系不误配；任务进度可查询，历史邮件不触发 Graph，初始化完成后重启跳过。

## A3：人工发布案例与运行期间导入产品文档

**依赖**：A2；A1 的模型配置检查可用。

**文件**：创建 `src/services/knowledge.py`、`src/services/chunking.py`、`src/repositories/knowledge.py`、`src/api/knowledge.py`、`src/api/cases.py`、`src/adapters/embedding.py`、`tests/fixtures/knowledge/`、`tests/integration/test_knowledge_publish.py`、`tests/unit/test_chunking.py`；按需修改现有评测适配器保持兼容。

**先写失败测试**：先验证未审核案例不能发布、重复确认复用候选、嵌入失败不暴露不完整新知识版本、路径穿越和工作区外链接被拒绝；无服务实现时失败。加入超长段落和超长案例，要求不静默截断且保留来源。

**最小实施步骤**：按已有 API 完成配对确认/拒绝、候选查询/审核/发布/归档；清洗脱敏并保留受控原文。产品文档通过可信相对路径导入，运行中无需重启；按标题与段落切分，保留来源及适用元数据。案例按结构化内容生成检索文本，保持问题与回复关联，受模型输入上限约束。相同内容和相同嵌入配置跳过重复嵌入；新版本完成后才供检索，旧引用仍可追溯。

**验证命令**：

```powershell
docker compose --env-file .env -f deploy/mvp/compose.yaml build api
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api python -m pytest tests/unit/test_chunking.py tests/unit/test_knowledge_embedding.py tests/integration/test_knowledge_publish.py tests/eval/test_redact.py tests/eval/test_local_embedding.py -q
```

**通过条件**：产品与已审核案例可入库；候选和归档版本不可召回；重试不重复发布；失败不污染有效知识，敏感信息不进入片段，历史引用保留。

## A4：用真实数据库完成双路知识召回

**依赖**：A3。

**文件**：创建 `src/services/retrieval.py`、`tests/integration/test_retrieval.py`、`tests/helpers/retrieval_live.py`、`migrations/versions/0004_retrieval.py`；修改 `src/repositories/knowledge.py`、`src/models.py`；复用 `evals/harness/normalize.py` 的已验证标识保护规则。

**先写失败测试**：先建立产品与案例各自的相关/干扰片段，验证每类最多三条、来源隔离、去重和仅 active 可见；没有 PostgreSQL 检索实现时失败。包含型号、错误码、无答案和仅案例命中。

**最小实施步骤**：实现英文全文检索、精确向量检索及既定 RRF 融合；明确型号和版本才过滤，不猜测未知值。检索返回片段 ID、内容、来源版本及排名，支持后续引用校验。RRF 只作为既定基线，记录参数，不通过保留集调优，不把返回 Top-3 当作证据充分。

**验证命令**：

```powershell
docker compose --env-file .env -f deploy/mvp/compose.yaml build api
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api python -m pytest tests/integration/test_retrieval.py tests/eval/test_normalize.py tests/eval/test_retrieve.py -q
```

**通过条件**：真实 PostgreSQL 两路检索符合来源、数量与版本约束，模型标识不一致明确失败，无答案可以返回候选但不被标为有依据。

本阶段目标测试通过后运行整体计划约定的相关回归，记录证据再更新状态账本。不要将本阶段通过等同于整个 MVP 或生产验证通过。
