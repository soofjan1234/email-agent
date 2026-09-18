"""业务持久化结构；Graph 内部状态交由后续 PostgreSQL Checkpointer 管理。"""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, CheckConstraint, Computed, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """共享声明式映射，不在应用启动时自动建表。"""


class Record:
    """业务记录使用 UUID 与数据库生成的 UTC 时间。"""
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MutableRecord(Record):
    """可更新记录保留最后修改时间。"""
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EmbeddingIndex(Base):
    """当前向量列绑定一个不可混用的编码身份，由迁移初始化。"""
    __tablename__ = 'embedding_indexes'
    __table_args__ = (CheckConstraint('id = 1', name='embedding_single_identity'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index_version: Mapped[str] = mapped_column(Text, unique=True)
    identity: Mapped[dict] = mapped_column(JSONB)


class Email(MutableRecord, Base):
    """邮件状态只是查询投影，不参与 Graph 路由。"""
    __tablename__ = 'emails'
    __table_args__ = (CheckConstraint('workflow_generation >= 1', name='email_generation_positive'),)
    client_request_id: Mapped[str] = mapped_column(Text, unique=True)
    from_address: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    graph_thread_id: Mapped[str | None] = mapped_column(Text, unique=True)
    workflow_generation: Mapped[int] = mapped_column(default=1, server_default='1')
    status: Mapped[str] = mapped_column(String(64), default='received', server_default='received')
    category: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(Text)
    risk: Mapped[str | None] = mapped_column(Text)
    reply_draft: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, default=list, server_default='[]')


class MailboxSyncState(Base):
    """每邮箱唯一的真实 IMAP 增量位置；UID 必须与 UIDVALIDITY 成对解释。"""
    __tablename__ = 'mailbox_sync_states'
    mailbox_id: Mapped[str] = mapped_column(Text, primary_key=True)
    uidvalidity: Mapped[str] = mapped_column(Text)
    last_committed_uid: Mapped[int] = mapped_column(Integer)
    history_sync_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('mail_sync_jobs.id'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class KnowledgeDocument(MutableRecord, Base):
    """发布产生新版本，历史引用通过外键保留。"""
    __tablename__ = 'knowledge_documents'
    __table_args__ = (
        UniqueConstraint('source_type', 'source_ref', 'version', name='document_source_version'),
        CheckConstraint("source_type IN ('product_doc', 'approved_case')", name='document_source_type'),
        CheckConstraint("status IN ('active', 'archived')", name='document_status'),
        CheckConstraint('version >= 1', name='document_positive_version'),
    )
    source_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default='active', server_default='active')
    content_hash: Mapped[str | None] = mapped_column(String(64))
    index_version: Mapped[str | None] = mapped_column(ForeignKey('embedding_indexes.index_version'))
    source_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, server_default='{}')
    # 受控原文仅用于数据库审计，普通知识和候选接口均不返回。
    raw_content: Mapped[str | None] = mapped_column(Text)


class KnowledgeChunk(Record, Base):
    """向量维度在迁移时从配置确定，ORM 写入另检查身份和值。"""
    __tablename__ = 'knowledge_chunks'
    __table_args__ = (UniqueConstraint('document_id', 'chunk_index', name='chunk_document_index'),
                      CheckConstraint('chunk_index >= 0', name='chunk_nonnegative_index'))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('knowledge_documents.id'))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector())
    index_version: Mapped[str] = mapped_column(ForeignKey('embedding_indexes.index_version'))
    product_model: Mapped[str | None] = mapped_column(Text)
    os_version: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)

    section_path: Mapped[list] = mapped_column(JSONB, default=list, server_default='[]')
    source_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, server_default='{}')
    token_count: Mapped[int | None] = mapped_column(Integer)
    # PostgreSQL 生成列与 GIN 索引服务英文全文召回；应用不直接写入该派生值。
    search_vector: Mapped[str] = mapped_column(TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True))


class Review(Record, Base):
    """每个 interrupt 只允许一个最终审核事实。"""
    __tablename__ = 'reviews'
    __table_args__ = (
        UniqueConstraint('graph_thread_id', 'checkpoint_id', name='review_interrupt'),
        CheckConstraint("action IN ('approve','edit_and_approve','reject','manual_review')", name='review_action'),
    )
    email_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('emails.id'))
    graph_thread_id: Mapped[str] = mapped_column(Text)
    checkpoint_id: Mapped[str] = mapped_column(Text)
    review_request_id: Mapped[str] = mapped_column(Text, unique=True)
    action: Mapped[str] = mapped_column(String(32))
    original_draft: Mapped[str] = mapped_column(Text)
    final_content: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, default=list, server_default='[]')
    model_version: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text)
    risk: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    result_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SimulatedOutbox(Record, Base):
    """审核唯一键防止节点重放时重复模拟发送。"""
    __tablename__ = 'simulated_outbox'
    email_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('emails.id'))
    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('reviews.id'), unique=True)
    to_address: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluationRun(Record, Base):
    """一次评估绑定不可变资料冻结、模型身份和随机种子。"""
    __tablename__ = 'evaluation_runs'
    __table_args__ = (
        UniqueConstraint('evaluation_run_id', name='evaluation_run_identifier'),
        CheckConstraint("purpose IN ('retrieval','draft_latency','review')", name='evaluation_run_purpose'),
    )
    evaluation_run_id: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(String(32))
    knowledge_freeze_sha256: Mapped[str] = mapped_column(String(64))
    embedding_identity: Mapped[dict] = mapped_column(JSONB)
    generator_identity: Mapped[dict | None] = mapped_column(JSONB)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    judge_model: Mapped[str | None] = mapped_column(Text)
    judge_prompt_version: Mapped[str | None] = mapped_column(Text)
    judge_run_id: Mapped[str | None] = mapped_column(Text)
    random_seed: Mapped[int] = mapped_column(Integer)
    code_version: Mapped[str] = mapped_column(Text)


class EvaluationSample(Record, Base):
    """评估样本在运行内冻结，只保存来源和纳入决定。"""
    __tablename__ = 'evaluation_samples'
    __table_args__ = (
        UniqueConstraint('evaluation_run_id', 'email_id', name='evaluation_sample_once'),
        CheckConstraint("sample_source IN ('real','synthetic_v2')", name='evaluation_sample_source'),
        CheckConstraint("(included AND exclusion_reason IS NULL) OR (NOT included AND exclusion_reason IS NOT NULL)",
                        name='evaluation_sample_inclusion_reason'),
    )
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('evaluation_runs.id'))
    email_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('emails.id'))
    sample_source: Mapped[str] = mapped_column(String(32))
    included: Mapped[bool] = mapped_column(Boolean)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)


class RetrievalObservation(Record, Base):
    """一个样本在一个固定检索通道中的候选或可审计失败。"""
    __tablename__ = 'retrieval_observations'
    __table_args__ = (
        UniqueConstraint('evaluation_sample_id', 'channel', 'raw_rank', name='retrieval_observation_rank'),
        CheckConstraint("channel IN ('keyword','vector','rrf')", name='retrieval_observation_channel'),
        CheckConstraint("status IN ('succeeded','empty','failed','timed_out')", name='retrieval_observation_status'),
        CheckConstraint('raw_rank >= 1', name='retrieval_observation_positive_rank'),
    )
    evaluation_sample_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('evaluation_samples.id'))
    channel: Mapped[str] = mapped_column(String(16))
    raw_rank: Mapped[int] = mapped_column(Integer)
    candidate_chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('knowledge_chunks.id'))
    candidate_version: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    failure_code: Mapped[str | None] = mapped_column(Text)


class RetrievalJudgment(Record, Base):
    """保留 Codex 初标与人工更正，任何更正不覆盖原始判定。"""
    __tablename__ = 'retrieval_judgments'
    __table_args__ = (
        UniqueConstraint('retrieval_observation_id', name='retrieval_judgment_observation_once'),
        CheckConstraint("codex_label IN ('relevant','partially_relevant','not_relevant','no_answer')",
                        name='retrieval_judgment_codex_label'),
        CheckConstraint("final_label IS NULL OR final_label IN ('relevant','partially_relevant','not_relevant','no_answer')",
                        name='retrieval_judgment_final_label'),
        CheckConstraint("audit_status IN ('pending','confirmed','corrected','unable_to_judge')",
                        name='retrieval_judgment_audit_status'),
    )
    retrieval_observation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('retrieval_observations.id'))
    blinded_rank: Mapped[int] = mapped_column(Integer)
    codex_label: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(Text)
    audit_status: Mapped[str] = mapped_column(String(32), default='pending', server_default='pending')
    final_label: Mapped[str | None] = mapped_column(String(32))


class EvaluationExecution(Record, Base):
    """草稿评估每次使用隔离执行邮件和新的 Graph thread。"""
    __tablename__ = 'evaluation_executions'
    __table_args__ = (
        UniqueConstraint('evaluation_run_id', 'source_email_id', 'attempt', name='evaluation_execution_attempt'),
        UniqueConstraint('execution_email_id', name='evaluation_execution_email_once'),
        CheckConstraint("status IN ('succeeded','failed','timed_out','archived')", name='evaluation_execution_status'),
        CheckConstraint('attempt >= 1', name='evaluation_execution_positive_attempt'),
    )
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('evaluation_runs.id'))
    source_email_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('emails.id'))
    execution_email_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('emails.id'))
    attempt: Mapped[int] = mapped_column(Integer)
    graph_thread_id: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(String(16))
    failure_code: Mapped[str | None] = mapped_column(Text)


class EvaluationSpan(Record, Base):
    """一条执行的阶段耗时、状态与受控重试次数。"""
    __tablename__ = 'evaluation_spans'
    __table_args__ = (
        UniqueConstraint('evaluation_execution_id', 'stage', name='evaluation_span_once'),
        CheckConstraint("status IN ('succeeded','failed','skipped')", name='evaluation_span_status'),
        CheckConstraint('duration_ms >= 0', name='evaluation_span_nonnegative_duration'),
        CheckConstraint('retry_count >= 0', name='evaluation_span_nonnegative_retry'),
    )
    evaluation_execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('evaluation_executions.id'))
    stage: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default='0')


class HistoricalEmailPair(MutableRecord, Base):
    """仅存确定的一对一配对，原文使用受控引用。"""
    __tablename__ = 'historical_email_pairs'
    __table_args__ = (
        UniqueConstraint('mailbox_id', 'inbound_message_id', name='pair_mailbox_inbound'),
        UniqueConstraint('mailbox_id', 'outbound_message_id', name='pair_mailbox_outbound'),
        CheckConstraint("pairing_method = 'header'", name='pair_header_only'),
        CheckConstraint("status IN ('paired','needs_review','rejected')", name='pair_status'),
        CheckConstraint('pairing_confidence >= 0 AND pairing_confidence <= 1', name='pair_confidence'),
    )
    mailbox_id: Mapped[str] = mapped_column(Text, default='local-mock', server_default='local-mock')
    sync_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('mail_sync_jobs.id'))
    inbound_message_id: Mapped[str] = mapped_column(Text)
    outbound_message_id: Mapped[str] = mapped_column(Text)
    inbound_ref: Mapped[str] = mapped_column(Text)
    outbound_ref: Mapped[str] = mapped_column(Text)
    pairing_method: Mapped[str] = mapped_column(Text, default='header', server_default='header')
    pairing_confidence: Mapped[float]
    status: Mapped[str] = mapped_column(Text, default='needs_review', server_default='needs_review')


class CaseCandidate(MutableRecord, Base):
    """候选按来源去重，人工审核版本与知识发布版本分别保存。"""
    __tablename__ = 'case_candidates'
    __table_args__ = (
        CheckConstraint('(email_pair_id IS NOT NULL AND email_id IS NULL AND review_id IS NULL) OR '
                        '(email_pair_id IS NULL AND email_id IS NOT NULL AND review_id IS NOT NULL)', name='candidate_one_source'),
        CheckConstraint("status IN ('candidate','reviewed','active','rejected','archived')", name='candidate_status'),
    )
    email_pair_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('historical_email_pairs.id'), unique=True)
    email_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('emails.id'))
    review_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('reviews.id'), unique=True)
    user_symptom: Mapped[str] = mapped_column(Text)
    applicability: Mapped[str] = mapped_column(Text)
    reply_template: Mapped[str] = mapped_column(Text)
    product_model: Mapped[str | None] = mapped_column(Text)
    os_version: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    risk_tags: Mapped[list] = mapped_column(JSONB, default=list, server_default='[]')
    redaction_result: Mapped[dict] = mapped_column(JSONB, default=dict, server_default='{}')
    review_comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default='candidate', server_default='candidate')
    published_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('knowledge_documents.id'))
    # 人工审核使用乐观版本，避免旧页面覆盖新审核或发布不同内容。
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    reviewer: Mapped[str | None] = mapped_column(Text)
    fact_sources: Mapped[list] = mapped_column(JSONB, default=list, server_default='[]')
    raw_review: Mapped[dict] = mapped_column(JSONB, default=dict, server_default='{}')


class AuditEvent(Record, Base):
    """保存关联标识及脱敏事件数据，不保存凭据或完整邮件。"""
    __tablename__ = 'audit_events'
    __table_args__ = (CheckConstraint("actor_type IN ('system','agent','human')", name='audit_actor'),)
    email_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('emails.id'))
    request_id: Mapped[str | None] = mapped_column(Text)
    graph_thread_id: Mapped[str | None] = mapped_column(Text)
    checkpoint_id: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default='{}')


class MailSyncJob(MutableRecord, Base):
    """Graph 外同步任务；历史初始化每邮箱唯一，进度与邮件同事务提交。"""
    __tablename__ = 'mail_sync_jobs'
    __table_args__ = (
        Index('history_job_mailbox', 'mailbox_id', unique=True,
              postgresql_where=text("mode = 'historical_backfill'")),
        UniqueConstraint('mailbox_id', 'sync_request_id', name='sync_request_mailbox'),
        CheckConstraint("mode IN ('historical_backfill','incremental')", name='sync_mode'),
        CheckConstraint("status IN ('pending','running','succeeded','failed')", name='sync_status'),
        CheckConstraint("stage IN ('snapshot','scanning','pairing','candidates','completed')", name='sync_stage'),
    )
    mailbox_id: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(Text)
    sync_request_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default='pending', server_default='pending')
    stage: Mapped[str] = mapped_column(Text, default='snapshot', server_default='snapshot')
    initialization_boundary: Mapped[dict | None] = mapped_column(JSONB)
    scan_cursor: Mapped[dict] = mapped_column(JSONB, default=lambda: {'inbox': 0, 'sent': 0},
                                            server_default='{"inbox":0,"sent":0}')
    scanned_count: Mapped[int] = mapped_column(default=0, server_default='0')
    added_count: Mapped[int] = mapped_column(default=0, server_default='0')
    skipped_count: Mapped[int] = mapped_column(default=0, server_default='0')
    failed_count: Mapped[int] = mapped_column(default=0, server_default='0')
    paired_count: Mapped[int] = mapped_column(default=0, server_default='0')
    candidate_count: Mapped[int] = mapped_column(default=0, server_default='0')
    unsupported_reasons: Mapped[dict] = mapped_column(JSONB, default=dict, server_default='{}')
    failure_type: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(default=False, server_default='false')
    cursor_before: Mapped[dict | None] = mapped_column(JSONB)
    cursor_after: Mapped[dict | None] = mapped_column(JSONB)


class MailSource(Record, Base):
    """固定文件集合及原始字节，原文仅存数据库，不通过任务 API 返回。"""
    __tablename__ = 'mail_sources'
    __table_args__ = (UniqueConstraint('sync_job_id', 'ordinal', name='source_job_ordinal'),
                      UniqueConstraint('sync_job_id', 'source_ref', name='source_job_path'),
                      CheckConstraint("folder IN ('inbox','sent')", name='source_folder'))
    sync_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('mail_sync_jobs.id'))
    ordinal: Mapped[int] = mapped_column(Integer)
    folder: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_content: Mapped[bytes] = mapped_column(LargeBinary)


class MailMessage(Record, Base):
    """历史邮件与新邮件业务表隔离，缺失或冲突协议头仍保存原文引用。"""
    __tablename__ = 'mail_messages'
    __table_args__ = (UniqueConstraint('mailbox_id', 'dedup_key', name='message_mailbox_identity'),)
    mailbox_id: Mapped[str] = mapped_column(Text)
    sync_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('mail_sync_jobs.id'))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('mail_sources.id'))
    dedup_key: Mapped[str] = mapped_column(String(64))
    folder: Mapped[str] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(Text)
    in_reply_to: Mapped[list] = mapped_column(JSONB)
    references: Mapped[list] = mapped_column(JSONB)
    from_address: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    parse_error: Mapped[str | None] = mapped_column(Text)
    unsupported_reason: Mapped[str | None] = mapped_column(Text)
