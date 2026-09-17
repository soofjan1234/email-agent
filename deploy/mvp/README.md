# MVP 本地启动与验证

应用提供数据库底座、A2 历史初始化及 A3 知识审核/发布和产品导入。API 启动登记任务，worker 自动扫描模拟邮箱、识别完整一对一关系并生成脱敏候选；候选经人工审核后才能发布，历史邮件不触发 Agent。阶段进度见[状态账本](../../docs/mvp/status.md)，验证证据见[验证记录](../../docs/mvp/validation.md)。

## 数据库与配置

优先复用本机 PostgreSQL。当前业务库为 `email_agent`，测试库为 `email_agent_snowflake_test`；旧 `email_agent_test` 保留历史测试记录，不再用于当前模型验证。其他机器需先创建业务库和独立测试库，并确保已安装 pgvector 扩展文件。首次迁移账户需要在目标库中创建扩展及业务表的权限。当前迁移版本为 `0003_knowledge`。

把根目录 `.env.example` 的配置填入忽略的 `.env`，不要覆盖已有模型凭据。原生进程使用 `DATABASE_URL`、`TEST_DATABASE_URL` 的 `localhost:5432`；Docker Desktop 使用 `MVP_DATABASE_URL`、`MVP_TEST_DATABASE_URL` 的 `host.docker.internal:5432`。密码需要使用 URL 编码；配置与凭据不进入镜像。

测试入口只接受名称以 `_test` 结尾、且名称不同于业务库的 PostgreSQL 数据库；不会清表或删除数据库。测试使用随机幂等键，可重复运行，会保留少量模拟记录。不要把业务库配置成测试库。

已有 `.env` 必须检查 `EMBEDDING_MODEL` 是否仍为旧网关别名；当前 TEI 服务身份为 `Snowflake/snowflake-arctic-embed-m-v1.5`。模型名与 revision 必须同时匹配。不能把已有向量直接重新标记为另一模型；本机空业务索引的历史配置修正和测试库切换证据见验证记录。

默认使用 Snowflake 开发候选、固定 revision、768 维、显式查询/文档前缀与 `dev-snowflake-m-v1.5-001` 索引。首次迁移把完整身份保存到数据库，并建立相应维度的向量列。模型、revision、模板、维度或索引版本变化时应用会拒绝启动/事务；不能只修改配置后混写旧列，应按后续迁移方案建立新索引并重新嵌入。此配置不是生产冻结。

## Docker Desktop

以下命令从仓库根目录执行。先确认本机 PostgreSQL 可连接，再执行一次性迁移；API/worker 不自动迁移。

首次启动 worker 前创建 `data/mock-mailbox/inbox/` 和 `data/mock-mailbox/sent/`，放入准备导入的历史 `.eml` 文件。Compose 将邮箱目录只读挂载到容器；`MAILBOX_ID` 必须与原生进程保持一致。空的两个目录会正常完成初始化；目录缺失则任务失败并保留可重试状态，不会被误判为空邮箱成功。

worker 首次成功捕获的文件集合、哈希和原始字节形成持久化边界。快照形成后新增的文件留给后续增量，文件修改不会改变当前历史处理结果。完成后重启跳过，不提供手动重复历史导入或时间范围选项。

```powershell
docker compose --env-file .env -f deploy/mvp/compose.yaml config --quiet
docker compose --env-file .env -f deploy/mvp/compose.yaml build api
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api alembic upgrade head
docker compose --env-file .env -f deploy/mvp/compose.yaml up -d api worker
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api python -m pytest -q
```

API 在 `http://127.0.0.1:8000`。`GET /health` 在数据库迁移、扩展和索引身份可用时返回 `200 {"status":"ok"}`，运行期间检查失败返回 503；启动检查失败则进程退出。可用 `docker compose --env-file .env -f deploy/mvp/compose.yaml stop api worker` 停止应用，不停止本机数据库。

备用 `postgres` 服务位于 `bundled-db` profile，默认不会启动。本轮未验收备用数据库部署；启用时还须将容器 URL 改为该服务的 `postgres:5432`、原生 URL 改为 `localhost:55432`，并匹配 Compose 中的开发角色。不要让同一部署的原生与容器入口指向不同数据库。

## Windows 原生调试

使用 Python 3.12。依赖锁文件包含本轮验证的全部直接与间接依赖；业务源码通过 `src` 搜索路径暴露，安装项目仅安装可复用的 `evals` 包。

```powershell
uv venv --python 3.12
uv pip sync requirements.lock
uv pip install --no-deps -e .
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = (Resolve-Path ./src).Path
try {
    .venv/Scripts/alembic.exe upgrade head
    .venv/Scripts/python.exe -m worker --once
    .venv/Scripts/python.exe -m pytest -q
    .venv/Scripts/uvicorn.exe main:app --app-dir src --loop asyncio:SelectorEventLoop
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
```

长期运行 worker 使用 `python -m worker`，不加 `--once`。当前 Uvicorn 的原生 Windows 默认循环不兼容 psycopg，因此 API 显式指定 Selector；worker、迁移和测试也使用兼容循环。

`--once` 会执行一次历史初始化，已成功则跳过；不是仅做健康检查。服务模式遇到可恢复失败会在后续轮询中继续处理。`MAIL_SYNC_PAGE_SIZE` 控制每个事务的处理数量，`WORKER_POLL_SECONDS` 控制恢复轮询间隔。

任务查询：`GET /api/v1/mail-sync-jobs`、`GET /api/v1/mail-sync-jobs/{id}`。可按 mode/status 分页查询；详情返回扫描游标、配对与候选数量、未支持原因以及失败信息，不返回原文。增量入口已实现初始化保护和幂等登记，实际增量处理与 Graph 调度仍待 B1；当前返回 202 的增量任务会保持 pending。

## 知识审核与产品导入

准备 `data/knowledge/`，把 UTF-8 Markdown 产品文档放在该目录内。原生配置 `KNOWLEDGE_ROOT=data/knowledge`，Compose 只读挂载到 `/app/data/knowledge`，因此更新宿主机文件后无需重建镜像或重启 API。`KNOWLEDGE_SOURCE_ID` 在原生和容器保持一致，默认 `local-products`；`KNOWLEDGE_MAX_BYTES` 默认 2000000。不支持绝对路径、目录穿越、符号链接或目录联接。

先启动既有本地 TEI 服务，或确认指定端点已运行匹配模型：

```powershell
docker compose -f deploy/embedding/compose.yaml up -d
```

等 `http://127.0.0.1:18080/info` 就绪并确认模型与 revision。原生使用 `EMBEDDING_BASE_URL=http://127.0.0.1:18080`，Compose 单独读取 `MVP_EMBEDDING_BASE_URL=http://host.docker.internal:18080`，避免原生 localhost 配置误指容器自身。

产品导入请求示例：

```powershell
$body = @{ path = 'nas/smb.md'; title = 'SMB guide'; product_model = 'NAS-X'; os_version = '2.1' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/knowledge/import -ContentType 'application/json' -Body $body
```

案例按“查询配对 → confirm → review → publish”操作。审核与发布需携带接口返回的 `revision` 作为 `expected_revision`；修改已发布案例重新审核并生成新知识版本。请求字段、拒绝/归档与错误语义见[接口契约](../../docs/mvp/architecture/api-design.md)。没有审核页面，原始内容只保存在受控数据库字段中。

真实模型冒烟只向配置的独立测试库写入公开合成样本；不包含检索质量或生产负载结论。先迁移测试库（常规 pytest 集成夹具会执行），再运行：

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
.venv/Scripts/python.exe tests/helpers/knowledge_live.py
```

该脚本验证长产品文档、长案例、末尾保留、脱敏、768 维向量及重复导入；输出仅包含安全计数和模型身份。无需模型的确定性回归仍使用 `python -m pytest -q`。

## 双路检索验证

A4 没有独立 HTTP 查询入口；它是后续邮件 Graph 使用的 `RetrievalService`。每次查询使用当前模型的查询角色生成向量，按 `product_doc` 和 `approved_case` 分别执行 PostgreSQL `english` 全文检索、pgvector 精确余弦检索和固定 `RRF=60` 融合。每类最多返回 3 条，返回片段及文档 ID、来源版本、两路名次和适用元数据；候选存在不表示已具备可靠依据。

首次升级会把 `knowledge_chunks.search_vector` 生成为数据库派生列，并创建 GIN 索引：

```powershell
.venv/Scripts/alembic.exe upgrade head
```

真实模型检索验证同样只使用独立测试库：

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
.venv/Scripts/python.exe tests/helpers/retrieval_live.py
```

它会建立唯一的产品和案例样本，验证 Snowflake 查询嵌入、型号/DSM 精确过滤、双来源候选和“不把候选当作充分依据”的返回边界。Docker 使用同一脚本：`docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api python tests/helpers/retrieval_live.py`。

重新解析依赖仅在有意升级时执行：`uv pip compile pyproject.toml --extra dev --python-version 3.12 --output-file requirements.lock`，随后重新验证两个运行环境。LangGraph 与 PostgreSQL Checkpointer 已锁定依赖；恢复和业务调度仍由 B1 实现及验证。
