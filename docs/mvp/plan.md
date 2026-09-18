# MVP 整体实施计划

依据 2026-09-16 用户确认的[总体设计](design.md)、[技术选型](architecture/tech-design.md)、[数据库设计](architecture/database-design.md)和[接口设计](architecture/api-design.md)。本计划保留产品文档与历史案例双路知识；实际交付进度唯一维护在[状态账本](status.md)。

## 1. 当前基础与执行边界

- 计划制定时已有 `evals/harness/`、`tests/eval/`、模型评测夹具和 `deploy/embedding/`，尚无业务应用；A1 执行后的真实进度统一见状态账本。
- 历史专项测试与模型报告作为可复用证据，不能替代真实 PostgreSQL、Graph 恢复、业务幂等或页面验收。
- 首次启动后台全量初始化 IMAP 收件和已发送邮件，之后恢复或跳过；明确 `unmatched` 的历史收件进入 B1 新邮件 Graph，其余历史记录不提供自动处理或历史范围选择。
- 产品文档可在运行期间导入；案例必须人工复核发布后才可检索。继续保留产品事实与案例措辞的职责区分。
- B1 实现只读真实 IMAP 增量，不实现真实 SMTP 发件、工单、复杂历史配对、多租户或多 Agent；不开展第二版的检索策略选优和阈值调参。
- 工作区已有未提交的评测与设计修改。执行前记录现状，按阶段检查差异，不覆盖或回滚无关改动，不把已有变更冒充本阶段交付。

## 2. 阶段与依赖

| 阶段 | 可交付结果 | 前置条件 | 子计划 |
| --- | --- | --- | --- |
| A | 自动导入历史邮件，复核发布案例，运行期间导入产品文档，并能从数据库检索两类知识 | 已确认设计 | [知识准备](plans/2026-09-16-mvp-knowledge.md) |
| B | 同步新邮件，生成有依据草稿，审核后模拟发送；中断可恢复且不重复产生业务记录 | A 的持久化、知识与检索可用 | [邮件闭环](plans/2026-09-16-mvp-workflow.md) |
| C | 英文页面完成知识管理和邮件审核，部署可复现，固定样例通过端到端验收 | A、B 完成相关自动检查 | [页面与验收](plans/2026-09-16-mvp-delivery.md) |

执行顺序：A1 → A2 → A3 → A4 → B1 → B2 → B3 → C1 → C2。允许在 A1 后提前运行 B1 的最小 PostgreSQL Checkpointer 探针，提前发现恢复阻断；不得因此跳过知识集成。每项测试应先以缺少目标行为失败，再完成最小实现并运行相关回归。

## 3. 代码落点与复用原则

以下是计划约定的代码落点；A、B 阶段的对应路径已经实现。业务源码直接放在 `src/`，不增加项目包名这一层；`src/` 是源码搜索起点，不作为导入包。评测包继续保留。`src/api/` 提供接口，`services/` 组织业务事务，`repositories/` 隐藏数据访问，`workflow/` 保存 Graph 定义，`adapters/` 封装邮箱与模型。`web/` 为 Vue 页面；`deploy/mvp/` 为应用 Compose；`tests/integration/` 必须使用独立真实 PostgreSQL 测试库。

可复用 `evals/harness/normalize.py`、`redact.py`、`agent_schema.py`、`embedder.py`、`generator.py` 中已验证的规则或适配代码。先读现有实现再提取必要的业务能力，评测通过兼容导入保留；不直接把评测运行器当作应用调度器。已有 `pairing.py` 的歧义拦截不能证明新版全量关联的一对一判定。

### 源码目录与导入约定

- `src/main.py`、`src/config.py`、`src/worker.py` 及 `src/api/`、`src/services/`、`src/repositories/`、`src/workflow/`、`src/adapters/` 直接承载应用代码。
- 各业务子目录建立 `__init__.py`；不创建 `src/__init__.py`，不使用 `from src...` 或 `from email_agent...`。统一使用 `from services...`、`from repositories...` 等绝对导入。
- API 从仓库根目录执行 `uvicorn main:app --app-dir src --loop asyncio:SelectorEventLoop`。worker 从仓库根目录执行 `python -m worker`，环境必须包含指向源码目录的 `PYTHONPATH`。
- Docker 将仓库复制到 `/app`，工作目录为 `/app`，统一设置 `PYTHONPATH=/app/src`；API、worker、Alembic 和容器测试共用该约定。Docker 构建须显式复制 `src/`，不依赖安装评测包来暴露业务源码。
- 原生 PowerShell 调试先执行 `$env:PYTHONPATH = (Resolve-Path ./src).Path`，再运行 worker 或迁移命令；使用完恢复原环境值。避免在模块内临时修改 `sys.path`。
- `pyproject.toml` 中 pytest 的 `pythonpath` 配置为 `["src", "."]`，分别支持业务模块与原有 `evals`；保留评测包发现配置，不将整个 `src` 错装成包，也不为本 MVP 额外设计业务 wheel 发布。
- A1 增加从仓库根目录和容器启动 API、worker，以及导入业务模块的冒烟检查，验证搜索路径而非仅确认目录存在。

## 4. 执行与验证约定

子计划中的新增命令由相应任务建立后执行。按 2026-09-16 用户要求优先复用本机 PostgreSQL，创建独立业务库和测试库；Docker/Linux 运行 API、worker，容器通过 `host.docker.internal` 连接本机库。备用 Compose PostgreSQL 仅在显式 profile 中启动。使用 `docker compose --env-file .env -f deploy/mvp/compose.yaml`；一次性迁移通过 `run --rm api alembic upgrade head`，不让 API/worker 并发迁移。原生 Windows API 须增加 `--loop asyncio:SelectorEventLoop`，详见[启动说明](../../deploy/mvp/README.md)。

每阶段目标测试通过后执行相关回归；最终执行 `docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api python -m pytest -q`，覆盖原有评测测试和新增测试。为测试显式配置独立 `TEST_DATABASE_URL`，测试必须拒绝业务数据库地址，禁止清空业务库。前端命令统一 `npm --prefix web ...`。最终检查 `git diff --check`，不自动提交或推送。

普通日志不含凭据或完整邮件。审计贯穿 request、email、thread、checkpoint 标识；代码常量、初始化、业务分步和核心算法按仓库约定补注释。新增 Python 多行辅助逻辑写脚本，不使用长 `python -c`。`.codex*`、`.gocache/`、运行数据与密钥继续忽略。

## 5. 验收映射

整体验收的唯一来源是 [MVP 范围第 6、7 节](README.md#6-业务验收场景)，下表只定位执行任务，不另设一套标准。

| 已确认要求 | 任务与证据 |
| --- | --- |
| 自动初始化、完整一对一、恢复与新增邮件边界 | A2 的跨批次、崩溃恢复和并发测试 |
| 脱敏、人工复核、产品导入、仅活跃知识可检索 | A3 的发布与版本测试 |
| 双路检索、标识词、来源和模型版本一致 | A4 数据库检索与身份验证 |
| 只匹配案例、无答案、缺信息、冲突、高风险 | B2 固定 Graph 路径与引用校验 |
| 提示注入、非法输出、超时、有限循环 | B2 失败注入与重试上限 |
| 垃圾邮件、VIP、普通邮件分类与条件路由 | B2 路径测试 |
| 审核四种动作、重启恢复、重复提交及节点重放 | B1、B3 的真实数据库与进程重启测试 |
| 审计、可编辑英文页面、模拟发件完整闭环 | C1 页面测试、C2 端到端验收 |
| 固定样例可复测，模型效果与业务可靠性分别报告 | C2 版本化数据与报告 |

## 6. 门槛与尚未完成的外部验证

Snowflake 是本地开发优先候选，不是生产冻结结论。A1 验证模型身份、输入角色、维度与长度；开发环境按明确的候选配置建独立索引，禁止使用旧 small 冻结记录默认确定维度。生产模型冻结继续依赖既有 Docker 对比计划中的独立标签复核、长输入、业务代表性和目标服务器验证。模型或输入配置变化时新建索引版本并重新嵌入，不混写向量。

现有 LLM JSON 冻结记录只证明历史夹具；B2 和 C2 必须增加真实数据库检索片段的契约验证。真实模型调用需要有效环境配置；缺少凭据时只报告 Fake 集成检查，不报告真实模型通过。

若实现发现新的接口字段、初始化边界策略或发布一致性决策无法由现有设计确定，先将具体问题与最小方案返回设计确认，再做依赖它的实现；不得用计划暗中变更契约。9.2、9.4 的 Markdown 适用范围在实现前核对：产品文档按章节切分，数据库案例无需额外落盘 `.md`；不得将此前讨论误解为允许所有长案例不受输入上限约束。

完成时在 `validation.md` 记录命令、环境、数据版本、报告位置及未完成项；更新账本。自动检查通过但缺必要外部验证时保持待验证，不能用计划写完或 Fake 通过宣称 MVP 已交付。
