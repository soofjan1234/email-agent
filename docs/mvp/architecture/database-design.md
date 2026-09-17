# NAS 售后邮件回复 Agent：数据库设计

## 1. 设计目标

数据库使用 PostgreSQL + pgvector，统一保存邮件处理、RAG 知识、历史案例、人工审核、模拟发件和审计数据。

核心约束：

- 模拟收件、人工审核和模拟发件均需幂等。
- 只有 `active` 产品文档和案例可以进入 RAG。
- 人工批准的回复只生成候选案例，不能直接进入知识库。
- LangGraph checkpoint 是 Agent 工作流运行状态的唯一来源，业务状态字段只作查询投影。
- 历史引用保留原版本，不因知识更新而失效。

## 2. 数据关系

```text
emails
  ├─ reviews
  │    └─ simulated_outbox
  ├─ case_candidates
  └─ audit_events

historical_email_pairs
  └─ case_candidates
       └─ knowledge_documents（发布后）

LangGraph Checkpointer
  └─ thread 状态、节点 checkpoint、interrupt 与恢复点
```

## 3. 表设计

### 3.1 `emails`

- `id`：内部 UUID；
- `client_request_id`：模拟收件幂等键，唯一；
- `from_address`、`subject`、`body_text`；
- `graph_thread_id`、`workflow_generation`；
- `status`：仅用于列表查询的最终一致投影，不参与 Graph 路由；
- `created_at`、`updated_at`。

### 3.2 `knowledge_documents`

- `id`、`source_type`、`title`、`version`；
- `source_type` 为 `product_doc` 或 `approved_case`；
- `source_ref`：来源文件或案例标识；
- `status`：`active` 或 `archived`；
- `created_at`、`updated_at`。

### 3.3 `knowledge_chunks`

- `id`、`document_id`、`chunk_index`；
- `content`、`embedding`；
- `product_model`、`os_version`、`category` 等过滤元数据；
- 文档版本变更时重新生成，不原地覆盖历史审计引用的内容。

A3 的 `0003_knowledge` 增量迁移增加：文档 `content_hash`、`index_version`、`source_metadata`、受控 `raw_content`；片段 `section_path`、`source_metadata`、`token_count`。来源元数据保留相对路径或候选标识、明确适用范围及案例审核来源。指纹覆盖清洗正文、标题、元数据、切分版本和完整模型身份；相同文本与索引身份的已有片段可复用向量，但新文档仍有独立片段 ID。

发布按来源取得 PostgreSQL 事务锁，完成所有嵌入后一次事务写入文档与片段、归档旧版本。任何写入或提交失败整体回滚；无半成品 active 版本。旧片段不删除，`active_chunks_statement()` 只选择有效文档的片段，为 A4 提供基础查询。

A4 的 `0004_retrieval` 迁移为 `knowledge_chunks.search_vector` 增加 PostgreSQL 生成列：`to_tsvector('english', content)`，并创建 `knowledge_chunk_search_gin` GIN 索引。应用不写该派生列；片段入库或更新时由数据库生成。全文和向量通道都限制 `knowledge_documents.status = active`、当前 `index_version` 与来源类型，显式识别到的 `DS...+`、`DSM x.y` 再作为精确元数据过滤。

### 3.4 `reviews`

- `id`、`email_id`、`graph_thread_id`、`checkpoint_id`；
- `review_request_id`：审核幂等键，唯一；
- `action`：`approve`、`edit_and_approve`、`reject`、`manual_review`；
- Graph interrupt 展示的原始草稿与最终确认内容；
- 最终采用的知识引用、模型与 Prompt 版本；
- 人工修正后的分类、优先级和风险；
- `reviewer`、`comment`、`created_at`。

### 3.5 `simulated_outbox`

- `id`、`email_id`、`review_id`；
- `to_address`、`subject`、`body_text`；
- `sent_at` 表示模拟发送时间；
- `review_id` 唯一，防止重复模拟发送。

### 3.6 `audit_events`

- `id`、`email_id`、`graph_thread_id`、`event_type`；
- `actor_type`：`system`、`agent`、`human`；
- 脱敏后的事件数据；
- `created_at`。

### 3.7 `historical_email_pairs`

- `id`：配对记录 UUID；
- `inbound_message_id`、`outbound_message_id`：历史收件与回复标识；
- `pairing_method`：MVP 仅使用 `header`，人工确认不改变协议头来源；模糊或手动建立关系留到第二版；
- `pairing_confidence`：只用于排序待审核配对，不作为自动发布条件；
- 原始邮件与回复的受控引用；
- `status`：`paired`、`needs_review` 或 `rejected`；
- `created_at`、`updated_at`。

本表仅保存全量关系识别后确定的一对一配对。每个收件和回复分别保持唯一，不能从复杂关联中拆出一对一记录。未匹配、复杂或不确定关系保留原始邮件与任务处理原因，不伪造配对记录。

### 3.8 `case_candidates`

- `id`、`email_pair_id` 或当前系统的 `email_id`、`review_id`；
- 清洗后的用户现象、适用条件、最终回复样板；
- 产品型号、系统版本、分类和风险标签；
- 脱敏结果与人工审核意见；
- `status`：`candidate`、`reviewed`、`active`、`rejected` 或 `archived`；
- `published_document_id`：发布后对应的 `knowledge_documents.id`；
- `created_at`、`updated_at`。

`active` 案例才能进入 RAG。`candidate` 和 `reviewed` 案例不得被检索，避免未经二次审核的回复污染知识库。

A3 增加 `revision`、`reviewer`、`fact_sources` 和受控 `raw_review`。所有修改按固定顺序锁配对和候选；`expected_revision` 防止过期审核/发布覆盖新内容。已发布案例重新审核时新修订为 reviewed，旧 published_document_id 保持有效直至新版本提交；这里只允许检索之前已审核发布的文档，不暴露新修订。原始人工输入不进入普通接口或审计事件，已发布文档保存对应原文快照。

### 3.9 历史初始化任务持久化

历史初始化任务属于 Graph 外的业务任务。持久化邮箱标识、初始化边界、收件与已发送邮件扫描位置、处理阶段、状态、失败原因及暂不支持关系的处理记录。

同一邮箱的初始化任务保持唯一，启动检查幂等创建或恢复；多进程不得重复执行。成功表示全部扫描、关系识别和候选生成完成，不能仅以拉取完成判定成功。邮件保存和扫描进度提交必须保证崩溃恢复不漏数据；历史候选按配对来源唯一。初始化完成后从保存的边界继续增量同步。

持久化实体：

- `mail_sync_jobs`：邮箱标识、模式、请求幂等键、状态、阶段、边界摘要、收件/发件游标、扫描与候选计数、未支持原因以及失败信息。历史模式按邮箱建立唯一部分索引。
- `mail_sources`：固定快照的文件序号、相对来源、目录类别、内容哈希和原始字节。快照成功提交后不再依赖源文件可用性；任务接口不返回这些原文。
- `mail_messages`：从快照解析的协议头、主题、正文及未支持原因，引用 `mail_sources`。按邮箱、目录、Message-ID 与内容哈希去重；相同 Message-ID 的不同原文全部保留并作为歧义排除。

`historical_email_pairs` 增加 `mailbox_id`、`sync_job_id`，每个邮箱内的收件与回复分别唯一，原文引用指向内部 `mail_messages` 标识；不把历史记录写入供新邮件 Graph 使用的 `emails` 表。

初始化使用固定文件集合及原始字节快照作为边界，两个目录的快照和边界摘要一次事务提交。后续按快照序号逐页读取，邮件与游标同事务提交；全量关联识别完成后，再逐页生成候选。执行期间使用同一 PostgreSQL 连接的邮箱会话锁，连接关闭即释放，已提交页保持可恢复，不增加租约状态机。

### 3.10 `embedding_indexes`

向量列通过单一索引身份记录绑定本次建库配置：`index_version`、模型、revision、维度、查询前缀和文档前缀。`knowledge_chunks.index_version` 外键引用该记录；向量列的实际维度在初次迁移时确定。应用启动和事务入口核对完整身份，写片段时继续验证维度、有限值及非零向量。

同一向量列不混用多个编码空间。模型或模板变更须通过独立索引/迁移和重新嵌入切换，不允许应用会话改写现有身份。该记录描述开发索引，不替代生产冻结记录。

审计基础额外保存 `request_id` 和 `checkpoint_id`，与邮件、Graph thread 标识共同关联请求及运行上下文。

## 4. 一致性与安全要求

- `client_request_id` 防止重复收件。
- `review_request_id` 防止重复审核。
- `simulated_outbox.review_id` 唯一，防止重复模拟发送。
- 同一邮件 workflow generation 的 `graph_thread_id` 唯一；重新处理创建新 generation，不复用已结束的 Graph。
- `reviews` 使用 `review_request_id` 幂等，并以 `graph_thread_id + checkpoint_id` 限制同一 interrupt 的最终审核结论。
- 人工审核记录、模拟发件和候选案例写入使用明确事务及唯一约束；节点重放不得产生重复副作用。
- `emails.status` 与 checkpoint 最终一致；审核和恢复前读取真实 interrupt，后台对账可修复投影。
- 案例发布后生成新的知识文档版本，不覆盖旧版本。
- 审计记录不保存模型密钥，普通日志不记录完整邮件正文。
- 邮箱、电话、地址、设备序列号、外网地址、账号和访问令牌在进入案例库前必须脱敏。

总体流程、状态机和知识生产规则见[总体设计](../design.md)。
