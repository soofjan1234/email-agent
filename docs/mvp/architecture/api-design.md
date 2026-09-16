# NAS 售后邮件回复 Agent：接口设计

## 1. 通用约定

- 接口统一使用 `/api/v1` 前缀和 JSON。
- 资源 ID 使用 UUID。
- 分页接口使用 `page` 和 `page_size`。
- 参数校验失败返回 `400`，资源不存在返回 `404`，幂等键内容冲突或状态冲突返回 `409`。
- 错误响应至少包含 `code`、`message` 和 `request_id`。
- 修改状态的接口必须携带幂等键或预期旧状态。
- 接口不得返回模型密钥、未脱敏凭据或不必要的完整审计数据。

## 2. 邮件同步

### `POST /api/v1/mail-sync-jobs`

用于用户触发最新邮件增量同步。请求字段：

- `sync_request_id`：同步请求幂等键；
- `mode`：仅接受 `incremental`。

MVP 不接受 `start_time`、`end_time` 或手动 `historical_backfill` 请求，提交这些参数返回 `400`。历史初始化由程序启动检查自动创建或恢复，规则见总体设计 6.2、6.3；内部任务仍使用 `historical_backfill` 模式。

第一版调用 `MockMailboxAdapter`。首次提交返回 `202` 和同步任务 ID；相同幂等键及相同参数返回已有任务，相同幂等键但参数不同返回 `409`。历史初始化未完成或同一邮箱已有运行中的同步任务时返回 `409`，避免并发拉取和历史邮件误入新邮件流程。

### `GET /api/v1/mail-sync-jobs`

按同步模式和状态查询任务，使用通用分页参数。页面通过该接口发现自动创建的历史初始化任务，无需用户先提交任务。

### `GET /api/v1/mail-sync-jobs/{id}`

返回：

- 同步模式；
- `pending`、`running`、`succeeded` 或 `failed` 状态；
- 已扫描、已新增、已跳过和失败的邮件数量；
- 初始化边界、扫描游标及配对与候选生成进度；
- 暂不支持关系的数量和原因；
- 失败类型和可重试信息。

历史任务只有完成全部扫描、关系识别和候选生成才标记成功。历史邮件不进入 Agent 回复流程，也不直接向量化；后续增量同步的新邮件才进入 Agent。

响应字段：`id`、`mode`、`status`、`stage`、`scanned_count`、`added_count`、`skipped_count`、`failed_count`、`initialization_boundary`、`scan_cursor`、`pairing_progress`、`candidate_progress`、`unsupported_count`、`unsupported_reasons`、`failure_type`、`retryable`。列表返回 `items`、`total`、`page`、`page_size`，每页最多 100 项。

`stage` 按 `snapshot → scanning → pairing → candidates → completed` 推进。扫描数量按物理文件计，新增数量按去重邮件计；失败数量表示保留了原文但解析失败的新增邮件，与新增数量可重叠。边界只返回快照 ID、捕获时间、摘要和文件数，不含磁盘路径或原文。未支持数量按去重邮件计，不是会话数。

A2 的增量入口只完成初始化保护和幂等任务登记，实际增量执行由 B1 接入；在该阶段提交成功的增量任务保持 pending，不表示已经同步了新邮件。

## 3. 邮件查询

### `GET /api/v1/emails`

支持按 `status`、`category` 和 `priority` 过滤，并使用 `page`、`page_size` 分页。`status` 是查询投影，不作为 LangGraph 流程控制依据。

### `GET /api/v1/emails/{id}`

返回原邮件、当前状态、Agent 建议、引用、回复草稿和审核历史。

## 4. 人工审核

### `POST /api/v1/emails/{id}/reviews`

请求包含：

- `review_request_id`；
- `graph_thread_id` 和 `checkpoint_id`，用于定位当前待处理 interrupt；
- 审核动作；
- 最终回复内容；
- 人工修正后的分类、优先级和风险；
- 审核意见。

重复请求使用 `review_request_id` 幂等。服务端必须确认指定 thread 当前停在匹配的人工审核 interrupt；不匹配、已经恢复或存在并发审核时返回 `409`。审核结果落库后，使用同一 `thread_id` 和 `Command(resume=...)` 恢复 Graph；`emails.status` 只用于页面列表展示，不能代替 interrupt 校验。

## 5. 模拟发件箱

- `GET /api/v1/outbox`；
- `GET /api/v1/outbox/{id}`。

模拟发送只写数据库，不执行任何网络请求。只有审核批准的回复才能生成模拟发件记录。

## 6. 产品知识导入

### `POST /api/v1/knowledge/import`

仅供本地管理操作使用。请求指定受信任的仓库内相对路径；后端禁止绝对路径、路径穿越和工作区外文件。

A3 请求示例：`{"path":"nas/smb.md","title":"SMB guide","product_model":"NAS-X","os_version":"2.1","category":"network"}`。仅 `path` 必填，路径相对于配置的 `KNOWLEDGE_ROOT`（默认 `data/knowledge`）；服务端不接受请求修改根目录。仅接受 UTF-8 Markdown，拒绝符号链接、目录联接及 Windows 数据流，默认文件上限 2 MB。适用字段由调用者明确提供，不从正文猜测。

成功返回 200，包含 `id`、`source_type`、`source_ref`、`title`、`version`、`status`、`index_version` 和脱敏 `metadata`，不返回受控原文。相同来源、内容和配置复用已有有效版本；变更生成新版本，全部片段准备完毕后在同一事务切换。`source_ref` 由稳定的 `KNOWLEDGE_SOURCE_ID` 与规范化相对路径组成，原生与容器需保持该标识一致。

非法路径或输入返回 400；模型不可用、身份不符、切分/嵌入失败返回固定 503 `knowledge_preparation_failed`，不回显模型响应或文档内容。失败不改变旧版本，调用者可安全重试。导入同步完成后返回，当前面向小规模本地知识，不提供后台导入任务。

## 7. 历史邮件配对

### `GET /api/v1/case-pairs`

通过 `sync_job_id` 和 `status` 查询历史初始化任务产生的确定一对一配对及待人工确认结果。

### `POST /api/v1/case-pairs/{id}/confirm`

确认或拒绝确定的一对一配对；确认时复用自动生成的候选案例。重复确认不得创建重复配对和候选案例。不支持将复杂或不确定关系通过本接口转为案例，状态不符合条件时返回 `409`。

请求为 `{"action":"confirm","reviewer":"operator"}`，`action` 也可为 `reject`。返回配对 `id`、`status` 和 `candidate_id`。拒绝会同步拒绝未发布候选；已有发布版本时须使用归档接口，不能通过拒绝配对撤销。列表额外支持 `page`、`page_size`（1—100），仅查询配置邮箱。

## 8. 候选案例审核与发布

### 查询

- `GET /api/v1/case-candidates?status=`；
- `GET /api/v1/case-candidates/{id}`。

### 审核

`POST /api/v1/case-candidates/{id}/review`

保存清洗、脱敏、适用条件和事实来源审核结果。

请求包含 `expected_revision`、`action`（`approve` 或 `reject`）、`reviewer`；批准时还必须填写非空 `user_symptom`、`applicability`、`reply_template`、`fact_sources`（来源字符串列表）。可选 `product_model`、`os_version`、`category`、`risk_tags`、`comment`。历史来源须先确认配对，过期版本或非法状态返回 409。

成功审核使 `revision` 加一，并返回脱敏候选详情。详情包含上述业务字段、`status`、`redaction_result`、`published_document_id`，不公开 `raw_review` 或历史邮件原文。列表按 `status`、`page`、`page_size` 分页。原始邮件和人工修订输入仅保存在受控数据库字段；页面对照与访问控制由 C1 接入。

### 发布

`POST /api/v1/case-candidates/{id}/publish`

请求为 `{"expected_revision":2}`。只有 `reviewed` 候选可以首次发布；切分与嵌入全部成功后，事务同时保存 `active approved_case`、片段、候选发布状态及审计。同一版本重试返回同一文档，不重复发布或嵌入。

修改已发布案例须重新审核，形成新的候选 revision；准备期间原文档继续有效，新文档完整提交后旧文档归档。候选的新修订在发布之前不可召回。此流程不原地修改历史片段。

### 归档

`POST /api/v1/case-candidates/{id}/archive`

停止检索已发布案例，但保留历史引用和审计记录。已发布案例的修改必须生成新版本。

请求为 `{"expected_revision":2,"reviewer":"operator"}`。归档可重复，返回候选详情；已归档案例不能通过旧发布请求重新激活。

## 运行检查

`GET /health` 用于应用依赖就绪检查，不属于邮件业务 API。迁移版本、pgvector 扩展及开发索引身份可用时返回 `200 {"status":"ok"}`；运行期间依赖检查失败返回 `503 {"detail":"database unavailable"}`，不返回连接信息。启动检查失败时进程退出，不接受请求。该检查不表示邮件业务流程或真实模型服务已经就绪。

数据库实体和幂等约束见[数据库设计](database-design.md)，总体流程见[总体设计](../design.md)。
