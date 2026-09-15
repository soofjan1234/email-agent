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
- `pairing_method`：`header`、`subject_time` 或 `manual`；
- `pairing_confidence`：只用于排序待审核配对，不作为自动发布条件；
- 原始邮件与回复的受控引用；
- `status`：`paired`、`needs_review` 或 `rejected`；
- `created_at`、`updated_at`。

### 3.8 `case_candidates`

- `id`、`email_pair_id` 或当前系统的 `email_id`、`review_id`；
- 清洗后的用户现象、适用条件、最终回复样板；
- 产品型号、系统版本、分类和风险标签；
- 脱敏结果与人工审核意见；
- `status`：`candidate`、`reviewed`、`active`、`rejected` 或 `archived`；
- `published_document_id`：发布后对应的 `knowledge_documents.id`；
- `created_at`、`updated_at`。

`active` 案例才能进入 RAG。`candidate` 和 `reviewed` 案例不得被检索，避免未经二次审核的回复污染知识库。

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

总体流程、状态机和知识生产规则见[总体设计](design.md)。
