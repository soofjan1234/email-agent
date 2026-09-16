# MVP 专项验证记录

> 2026-09-15 路线变更：Embedding 已转为 [Docker 开放模型对比设计](designs/2026-09-13-embedding-truth-test-design.md)。下列 OpenAI 与公司 Qwen 结果均为历史证据；旧冻结文件保留，但不再作为新部署的建库依据。本机容器历史集冒烟及扩展集三轮对比已完成，独立标注复核与生产验证待完成，见本页末节。

本页汇总已有评测证据及本地回归结果，不重新定义验收标准。专项通过条件见 [MVP 入口中的验证设计](README.md#专项验证材料)，整体完成条件见 [MVP 范围](README.md)。工作进度以[主题状态](status.md)为准。

## 2026-09-13 已提交的评测记录

| 专项 | 仓库记录 | 证据 |
| --- | --- | --- |
| Embedding | `text-embedding-3-small`，1536 维；产品文档与案例 Recall@3 均为 1.0 | [冻结记录](../../evals/embedding-v1/freeze.json) |
| LLM JSON | `gpt-4o-mini`，`json_schema`；Schema 合法率 1.0，引用和安全检查通过 | [冻结记录](../../evals/llm-json-v1/freeze.json) |
| 英文规范化、配对与脱敏 | 保存了英文规则版本、协议头优先配对及脱敏占位符 | [冻结记录](../../evals/text-v1/freeze.json) |

以上为周末提交中保存的结果，2026-09-15 未重跑这些已冻结模型；当日新增 Qwen 补测见下节。冻结文件仅保留摘要，不能据此宣称大规模效果、生产稳定性或端到端集成已验证。运行方式与夹具分别见 [Embedding](../../evals/embedding-v1/README.md)、[LLM JSON](../../evals/llm-json-v1/README.md)、[文本处理](../../evals/text-v1/README.md)。

## 2026-09-15 Qwen3 Embedding 0.6B 真实接口补测

结论：`local_server` 的 `qwen3-embedding:0.6b` 通过现有英文小样本门槛，实测向量为 1024 维。本次补测当时保留了 `text-embedding-3-small` / 1536 的冻结记录，未触发模型切换；后续路线已变更，见页首说明。

- 接口：`http://192.168.100.102:30000/v1/embeddings`，复用 `HttpEmbedder` 和 `evaluate_model`，原始文本输入，不添加任务指令。
- 规模：17 条片段（产品文档 10、案例 7），14 条英文查询；其中 13 条有相关答案、1 条知识库外查询不计入 Recall。
- 标准：两路 Recall@3 ≥ 0.80、标识查询全部进入 Top-3、向量维度一致。本轮额外确认两批均为 1024 维，所有向量数值有限且非零。

| 分路 | 计分查询 | Recall@1 | Recall@3 | MRR |
| --- | --- | --- | --- | --- |
| 产品文档 | 8 | 1.0 | 1.0 | 1.0 |
| 已审核案例 | 5 | 1.0 | 1.0 | 1.0 |

5 条标识查询全部命中。知识库外查询仍返回 Top-3 候选，当前评测没有拒答阈值，不能据此声称支持无答案判断。

端到端批次耗时：17 条语料 53.84 秒、14 条查询 13.76 秒，合计 67.60 秒。这是一次顺序运行，包含网络、排队及可能的模型加载；未单独测冷启动、稳态延迟、并发吞吐、硬件占用或费用。未重跑 OpenAI 对照；其历史冻结记录的两路 Recall@3 也是 1.0，但未保存数据集哈希，严格的同版本对照仍需重跑。当前结果不能证明 Qwen 优于 OpenAI。

证据：[逐查询排名、批次耗时和数据集 SHA-256](../../evals/embedding-v1/reports/2026-09-15-qwen3-embedding-0.6b.json)。报告不含凭据和向量全文。相关适配器、运行器、夹具、指标及检索回归共 12 项通过（`python -m pytest tests/eval/test_embedder.py tests/eval/test_runner.py tests/eval/test_dataset_contract.py tests/eval/test_metrics.py tests/eval/test_retrieve.py -q`）。

## 2026-09-15 本地回归

在 Windows、Python 3.12 的项目虚拟环境中执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

结果：32 项测试通过。该结果证明现有自动测试在本机通过，不代表真实网关评测重跑。

PostgreSQL 检索、LangGraph Checkpointer、审核恢复、有限循环和业务副作用幂等仍需在业务实现中完成集成验证，具体要求见[技术选型第 15 节](architecture/tech-design.md#15-分阶段技术验证)。


## 2026-09-15 本机 Docker 四模型冒烟

环境：Windows Docker Desktop Linux 引擎，单服务顺序执行，容器限制 4 CPU / 8 GiB，TEI 1.9.3（cpu-1.9 固定 digest）。修正后统一采用 512 batch tokens、每次最多 4 条输入；客户端显式禁止截断。本次是接入与历史夹具验证，不是正式模型选优或稳态性能测试。

对象：17 条片段、14 条英文查询；两路计分查询为 8 和 5，另有 1 条知识库外查询，标识查询 5 条。查询/文档按各模型官方输入规则处理，模型与 revision 均通过服务 `/info` 校验。

| 模型 | 维度 | 产品 Recall@3 | 案例 Recall@3 | 标识命中 | 编码请求总耗时（秒） |
| --- | --- | --- | --- | --- | --- |
| snowflake | 768 | 1.000 | 1.000 | 5/5 | 1.29 |
| nomic | 768 | 1.000 | 1.000 | 5/5 | 1.87 |
| bge-m3 | 1024 | 1.000 | 1.000 | 5/5 | 4.25 |
| qwen3 | 1024 | 1.000 | 0.800 | 5/5 | 17.46 |

耗时为同一轮所有文档与查询 HTTP 请求之和，可能包含首次请求的运行时影响，不含启动和下载；不能解释为单查询 p95。容器资源记录是运行后单次快照，不是峰值内存。逐查询排名、输入模板、数据哈希和批次耗时分别见：

- [Snowflake](../../evals/embedding-v1/reports/docker-2026-09-15-retry/snowflake.json)
- [Nomic](../../evals/embedding-v1/reports/docker-2026-09-15-retry/nomic.json)
- [BGE-M3](../../evals/embedding-v1/reports/docker-2026-09-15-retry/bge-m3.json)
- [Qwen3](../../evals/embedding-v1/reports/docker-2026-09-15-retry/qwen3.json)
- [启动时间、镜像身份和运行后资源快照](../../evals/embedding-v1/reports/docker-2026-09-15-retry/deployment.json)

初轮问题与修正：Snowflake 的 8 条输入超过 4 个并发槽位返回 429，统一拆成 4 条后重跑；Nomic 最新配置的别名字段被 TEI 视为重复，固定到官方前一兼容 revision；BGE-M3 首次下载超过 10 分钟就绪等待，保留缓存后续跑；Qwen 缺少 ONNX，TEI 自动转用 Candle 加载官方 safetensors，预热改为共同短文本配置后重跑。初轮[部署记录](../../evals/embedding-v1/reports/docker-2026-09-15/deployment.json)是排查证据，不能当作最终质量结论，其中 Qwen 的未就绪状态包含重建容器对观察器的影响。

相关代码全套自动测试 42 项通过，原网关接口与新入口保持兼容；当前实际使用一套 TEI Compose，配置及文档链接检查通过。实验结束后停止本次服务，保留模型缓存。旧 `freeze.json` 未修改。

### Qwen 输入指令消融

指令版漏掉 `q-case-no-format`（查询要求找到承诺不提供格式化或初始化步骤的已审核回复）。保持同一模型 revision、容器配置及夹具，仅移除查询指令后，产品路仍为 Recall@1/3=1.0；案例路 Recall@1=0.8、Recall@3=1.0、MRR=0.9，标识仍全部命中。详见[裸查询报告](../../evals/embedding-v1/reports/docker-2026-09-15-retry/qwen3-raw.json)。

这段保留早期观察。后续扩展集复现了 TEI 1.9.3 Qwen 等长批次缺陷，指令变化也可能改变批次组成，因此当前不能将这次排名差异单独归因于输入指令。旧 Docker Qwen 分数不作为可靠选优证据；公司原服务属于另一运行环境，不能自动外推此缺陷。正式模板调优仍应只用开发集，保留集固定评估。

以上为历史冒烟阶段记录；扩展集与重复测量已在下节完成，独立标注复核和生产冻结仍待完成。

## 2026-09-15 扩展集与四模型串行重测

完成 104 条英文片段、128 条查询：开发集 40、保留集 88，按 26 组混淆场景隔离；共 120 条计分查询、16 条双问题和 8 条无答案。虚构 ArcNAS 产品规则与批准回复由同一作者编写，尚未经独立人工复核。

初轮发现 Qwen 等长批次向量异常，已实际复现并采取单输入、单并发规避；四模型全部在该统一配置下重新跑三轮，未改数据、标签、权重或前缀。详细原因、原始及修正探针见[排查记录](../../evals/embedding-v2/QWEN-BATCH-ISSUE.md)。原四输入 Qwen 分数不能用来证明模型质量差。

保留集两路各 42 条计分查询，以下是重测首轮；重复轮次与完整逐题结果见[扩展集报告](../../evals/embedding-v2/RESULTS.md)。

| 模型 | 产品 R@3 | 回复 R@3 | 产品 MRR@3 | 回复 MRR@3 | 标识 Top-3 | 查询 P95（ms） |
| --- | --- | --- | --- | --- | --- | --- |
| snowflake | 100.00% | 100.00% | 0.9405 | 0.9643 | 19/19 | 58.0 |
| nomic | 98.81% | 100.00% | 0.9484 | 0.9365 | 19/19 | 79.0 |
| bge-m3 | 98.81% | 100.00% | 0.9524 | 0.9405 | 19/19 | 205.1 |
| qwen3 | 100.00% | 97.62% | 0.9167 | 0.9524 | 19/19 | 721.1 |

环境：本机 i7-11700F、Docker Linux、TEI 1.9.3、float32，容器限制 4 CPU / 8 GiB。每模型三轮共有 384 个查询单输入请求；P95 不含启动、下载、显式预热和检索计算，不是完整邮件处理时延。资源为运行期间 Docker stats 采样最大值，不是精确峰值。实际分词包含前缀，全部输入在本次 512 token 服务限制内，编码显式禁止截断。

新夹具结构、批次缺陷防护和汇总哈希检查加入后，`pytest -q` 共 48 项通过。检查了十二份最终报告的模型身份、输入哈希、向量维度、请求形状与重复排名，历史 v1 数据与冻结文件未改；实验容器已停止，缓存保留。

已完成用户请求的本地扩展测试，整体生产选型计划仍为待验证：独立人工标签复核、真实业务代表性、长输入与目标服务器尚未验证。无答案查询保留候选但未校准拒答阈值；没有生成回复或引用正确率结论，不新建生产冻结记录。

## 2026-09-16 A1 应用与真实数据库底座

用户确认执行 A1，并指定优先复用本机 PostgreSQL。已新建 `email_agent`（业务）和 `email_agent_test`（测试），没有清理或复用其他业务库。原生环境通过 `localhost:5432`，Docker Desktop 通过 `host.docker.internal:5432` 连接同一服务器。凭据只保存于忽略的 `.env`；备用 PostgreSQL 容器未启动，其部署未验收。

环境与依赖：Windows Python 3.12.1；容器 Python 3.12.13 / Debian bookworm；本机 PostgreSQL 17.6、pgvector 扩展 0.8.2。已验证 FastAPI 0.141.1、SQLAlchemy 2.0.54、psycopg 3.3.5、Alembic 1.20.0、pgvector Python 0.5.0、LangGraph 1.2.11、PostgreSQL Checkpointer 3.1.2 的安装依赖兼容性。直接依赖固定于 `pyproject.toml`，63 项解析依赖固定于 `requirements.lock`；依赖可安装不代表 Graph 恢复已验证。

实现内容：`src/` 下的 API 与 worker 入口、独立连接池与异步事务、九张基础表及 `0001_business` 迁移、审计关联字段、显式索引身份和向量写入校验；业务子目录包含 `__init__.py`，没有 `src/__init__.py`。历史任务持久化和处理逻辑留给 A2。API 只提供依赖检查，worker 只检查依赖并等待退出。

本次索引配置为 `dev-snowflake-m-v1.5-001`，Snowflake revision `e58a8f756156a1293d763f17e3aae643474e9b8a`，数据库实际列类型确认是 `vector(768)`。模型、revision、查询/文档模板、维度和索引版本共同参与一致性校验，不读取旧 small 冻结记录决定列维度。没有更改生产模型冻结状态。

本轮验证命令与结果（仓库根目录执行）：

| 验证 | 实际结果 |
| --- | --- |
| 新增 A1 测试的初始运行 | 安装依赖后因缺少 `main`、`db` 模块而失败，随后实现 |
| 原生 `alembic upgrade head` 与测试夹具重复迁移 | 两个新库均建立 `0001_business`，重复执行无重复建表或数据覆盖 |
| `.venv/Scripts/python.exe -m pytest -q` | 66 项通过，9.36 秒；原有评测 48 项、A1 集成 13 项、配置与协议边界 5 项 |
| `docker compose --env-file .env -f deploy/mvp/compose.yaml config --quiet` | 通过，凭据不输出 |
| 同一 Compose 的 `build api` | 镜像构建成功，依赖按锁文件安装，源码与评测包均可导入 |
| 同一 Compose 的 `run --rm api alembic upgrade head` | 容器连接本机业务库，重复迁移通过 |
| 同一 Compose 的 `run --rm api python -m pytest -q` | 66 项通过，9.56 秒；使用独立本机测试库 |
| `uv pip check` / 容器 `pip check` | 无依赖兼容性错误 |
| `git diff --check`、新增文件空白与本轮文档链接检查 | 通过；本机数据库密码未出现在新增源码、迁移、测试和部署模板中 |
| 同一 Compose 的 `up -d api worker` 与 HTTP 检查 | API 与 worker 成功启动，`GET /health` 返回 200；测试还分别从原生/容器根目录启动独立 API、worker 进程 |

测试验证邮件及审计真实读写、数据库唯一约束、完整配置身份不匹配拒绝、错误维度/零向量/非有限值拒绝并回滚、正常向量往返，以及测试库地址保护。另复用 TEI 适配器进行受控 HTTP 响应测试，确认显式查询/文档前缀和 `truncate=false`；本轮没有调用真实 Embedding 或 LLM 服务，没有长文本真实推理质量结论。

验证时业务库邮件数为 0，模拟邮件只写入测试库；没有清表。测试结束后停止本次启动的 API、worker 容器，保留两个项目数据库，本机 PostgreSQL 保持运行。启动命令见[运行说明](../../deploy/mvp/README.md)。A1 已通过，A2—A4、邮件 Graph、人工审核和页面均未由本轮交付，整体计划与知识阶段仍为待实现。

## 2026-09-16 A2 历史初始化与候选生成

已实现启动幂等登记、后台固定快照、分批持久化、完整关联识别、脱敏候选、任务列表/详情与增量入口保护。初始化由 `snapshot → scanning → pairing → candidates → completed` 推进，只有候选生成完成才成功。独立 worker 执行历史任务，API 启动不扫描文件；历史原文保存在独立表，不创建新邮件 Graph，也不发布或嵌入知识。

沿用 A1 的 Windows Python 3.12.1、容器 Python 3.12.13、本机 PostgreSQL 17.6 / pgvector 0.8.2 和依赖锁定结果。业务库、测试库均已通过独立命令升级至 `0002_history`；没有改写 `0001_business`。初始化使用一个持有 PostgreSQL 邮箱会话锁的连接执行全部分批事务，进程断开后锁自动释放。

公开夹具位于 `tests/fixtures/mailbox/`：7 个 `.eml` 文件，包含一个完全重复的文件；去重后 6 封邮件，其中 2 封构成一对一、3 封属于跨批次复杂会话、1 封未匹配。以每批 1 个文件处理，最终产生 1 个 candidate、3 个 complex_relationship 和 1 个 unmatched，未生成 active 知识。夹具哈希为 `21d6979d36b5f8bbfda6498e5bf0cff1dcdde5a1018f7d0bd840b6a019b58b29`（按相对路径排序，逐条追加路径、NUL 与原始字节后计算 SHA-256）。

| 验证 | 实际结果 |
| --- | --- |
| 初始目标测试 | 因缺少 `services.pairing`、`adapters.mailbox` 而失败，再补实现 |
| A2 目标及配对/脱敏回归 | 24 项通过，包含真实 PostgreSQL 和真实子进程 |
| Windows `python -m pytest -q` | 最终 89 项通过，17.44 秒 |
| Compose `build api` | 重建成功，包含最新源码、迁移和测试 |
| Compose `run --rm api alembic upgrade head` | 连接本机业务库，A1 → A2 升级成功 |
| Compose `run --rm api python -m pytest -q` | 最终 89 项通过，24.84 秒；数据库为本机独立测试库 |
| Compose `config --quiet` | 配置通过，模拟邮箱只读挂载，本机 PostgreSQL 仍是默认依赖 |

上述 Compose 命令统一使用 `docker compose --env-file .env -f deploy/mvp/compose.yaml`。三个 MVP 子计划与总计划的命令已同步显式 `.env`，后续独立验证块先重建镜像；C2 默认仅启动应用服务，备用 PostgreSQL 不自动启动。C2 的 web、live 模型等命令仍需后续实现，不作为本轮执行结果。

关键故障证据：

- 在第二页已写入数据库、尚未更新游标时通过 `os._exit(23)` 终止子进程：第一页和游标 1 保留，第二页事务回滚；新进程完成后仍为 7 个扫描文件、6 封去重邮件和 1 个候选。
- 两个独立子进程同时启动：只有一个报告执行，任务、7 份快照和候选均没有重复；另一项测试在持有邮箱锁时启动独立进程，确认其跳过执行。
- 快照提交后修改原文件并加入新邮件：历史结果仍使用原始字节，新增邮件没有进入本次历史任务，留待 B1 增量接入。
- 相同 Message-ID 的不同原文被保留，并排除整个相关分量；一对多、多对一、多对多、多跳 References、未知祖先、无协议头及空邮箱均有检查。
- 邮箱目录缺失时任务 failed 且可重试；补齐目录后恢复同一任务。API 验证了初始化期间 409、非法历史模式/时间范围 400、任务查询/分页、404 和重复增量请求复用任务。

收尾补充两项恢复回归，先复现“失效连接重连写失败状态”和“成功提交后被异常覆盖成失败”，再修复：丢失锁连接后旧执行者不再写状态；数据库中已提交的成功事实不被后续异常撤销。连接失效测试只关闭当前测试连接，没有停止本机 PostgreSQL，也不代表服务器故障切换验证。

最终 89 项包括原有 66 项及 A2 新增 23 项。MIME 检查覆盖纯文本正文选择、附件排除与非法协议头；不支持的正文格式保存原文和原因，不用于生成候选。清洗脱敏复用既有规则，候选仍需 A3 人工复核，未验证真实客户邮件覆盖率或大规模邮箱吞吐。文档相对链接、新增文件空白及 `git diff --check` 均通过。

本轮所有样例和故障注入仅使用 `email_agent_test`。最终检查 `email_agent` 的 `emails`、`mail_sync_jobs`、`mail_messages`、`case_candidates` 均为 0；尚未启动业务邮箱初始化。默认启动前需按[运行说明](../../deploy/mvp/README.md)准备历史文件。增量入口只登记 pending 任务，其实际读取和 Graph 调度由 B1 实现；人工发布、知识检索、真实模型和页面不属于本轮通过结论。

## 2026-09-16 A3 案例审核发布与产品文档导入

已实现配对确认/拒绝、候选查询/审核/发布/归档和运行期间 Markdown 产品导入。新增 `0003_knowledge`，保留历史表和数据，补齐内容指纹、模型索引引用、章节/token 信息和受控审核原文。来源事务锁串行化版本生成；全部嵌入和片段写入成功后，文档版本、旧版本归档、候选状态和审计才一并提交。

环境仍为本机 PostgreSQL 17.6 / pgvector 0.8.2、Windows Python 3.12.1 和容器 Python 3.12.13。本轮没有新增依赖或修改生产模型冻结记录。

### 配置问题与修正

真实 TEI 验证首先被身份检查拒绝。定位发现 `.env` 的 `EMBEDDING_MODEL` 仍为旧网关别名 `qwen3-embedding:0.6b`，业务及测试库初始身份也使用该名称，但 revision、768 维与索引标识均为 Snowflake 配置。A1/A2 只验证配置与数据库自洽及模型替身，不能证明当时的实际服务身份；此前的 Snowflake 描述应理解为预期开发候选。

本轮先确认业务 `knowledge_chunks` 为 0，再在锁住索引表和片段表的事务内核对旧身份、检查空库并修正为 `Snowflake/snowflake-arctic-embed-m-v1.5`；没有重新标记任何已有向量。旧 `email_agent_test` 保留，另建 `email_agent_snowflake_test`，使用正确身份从初始迁移建立独立测试库。`.env` 只更新模型名和两项测试库 URL，业务连接及已有网关凭据保留。以后有向量的索引必须另建索引并重嵌入，不能套用本次空库修正。

本机 TEI 的 `/tokenize` 即使单输入也返回批次二维列表；用真实响应修正协议测试和解析，客户端固定发送单元素列表。另将 Compose 的模型地址改为独立的 `MVP_EMBEDDING_BASE_URL`，避免 `.env` 的原生 localhost 地址覆盖容器 host 地址。

### 自动验证

| 验证 | 实际结果 |
| --- | --- |
| 初始 A3 测试 | 因缺少 `services.chunking`、`services.knowledge` 失败，再实现 |
| 目标测试与既有脱敏/TEI 回归 | 46 项通过；后续真实 tokenizer 响应修正已纳入最终回归 |
| Windows `.venv/Scripts/python.exe -m pytest -q` | 119 项通过，25.36 秒 |
| Compose `build api` | 成功；新增真实模型辅助脚本后再次重建成功 |
| Compose `run --rm api python -m pytest -q` | 119 项通过，28.74 秒 |
| Compose `config --quiet` | 通过；产品目录只读挂载，数据库继续使用本机 PostgreSQL |
| Windows 与容器 `python tests/helpers/knowledge_live.py` | 均通过真实 TEI 和独立 PostgreSQL 写入验证，结果见下表 |

上述 Compose 均以 `docker compose --env-file .env -f deploy/mvp/compose.yaml` 为前缀。119 项由已有 89 项和 A3 新增 30 项组成；常规回归的模型边界使用确定性替身，真实模型验证另行执行。没有把模拟向量测试作为真实模型推理证据。

关键回归覆盖：未确认/未审核/过期 revision 拒绝；重复确认复用候选；空白事实来源拒绝；配对拒绝不能绕过已发布案例归档；长段落和案例保留末尾；标题来源、代码围栏和产品引用提示保留；敏感值不进入模型或普通响应；非法路径、Windows 路径/数据流、工作区外链接拒绝；并发导入复用一个版本；部分嵌入失败保持旧版本；真实数据库写完片段后注入提交失败，确认回滚并可从版本 1 重试；已发布案例修订保留旧引用；仅元数据变化时复用向量；归档片段仍存在但不出现在 active 基础查询。

测试先复现后修复的行为问题包括：空白来源绕过审核、修订中的已发布案例被配对拒绝、元数据变化重复嵌入，以及真实 tokenizer 批次形状不符。模型失败对外固定返回 503，不复制上游错误正文。

### 真实模型冒烟

使用现有缓存启动 Snowflake TEI；实际 `/info` 核验模型 `Snowflake/snowflake-arctic-embed-m-v1.5`、revision `e58a8f756156a1293d763f17e3aae643474e9b8a`、最大输入 512 token。脚本生成一份超过模型单次上限的英文产品段落和一份长回复案例，通过真实 HTTP 适配器切分/嵌入、API 和 PostgreSQL 持久化。每次使用唯一测试来源，重复导入返回同一文档。

| 对象 | 片段数 | 最大实际 token 数 | 向量维度 | 检查 |
| --- | --- | --- | --- | --- |
| 产品文档：240 次排查句及末尾风险提示 | 4 | 504 | 768 | 末尾警告保留、邮箱已脱敏、引用段落保留 |
| 审核案例：220 次回复句及末尾步骤 | 7 | 352 | 768 | 问答同一来源、末尾步骤保留、邮箱已脱敏 |

原生与容器结果一致。`truncate=false` 与 token 计数共同约束输入；未测量检索准确率、回复质量、大规模吞吐或生产稳定性。切分、审核、发布为小规模同步处理；通用脱敏规则仍需人工复核，不能宣称覆盖所有真实敏感信息。

所有本轮样本保存在独立测试库；业务库仅升级迁移及修正空索引身份。A3 的通过不代表 A4 双路检索、B 阶段邮件 Graph 或 C 阶段页面完成。可复现命令及目录配置见[运行说明](../../deploy/mvp/README.md)。

最终检查：业务库迁移为 `0003_knowledge`，正确 Snowflake 身份已持久化，`knowledge_chunks`、`emails`、`mail_sync_jobs`、`case_candidates` 均为 0。`git diff --check`、新增源码语法/空白和本轮文档相对链接检查通过。临时模型服务已停止，没有启动长期 API/worker；本机 PostgreSQL 和三个项目数据库保留。代码未提交或推送。
