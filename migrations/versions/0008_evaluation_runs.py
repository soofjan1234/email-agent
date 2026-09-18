"""评估运行、冻结样本、检索判定和草稿 span 的审计表。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0008_evaluation_runs'
down_revision = '0007_workflow_projection'
branch_labels = None
depends_on = None


def upgrade():
    """创建不可变评估事实表，按运行 ID 建立读取索引。"""
    op.create_table('evaluation_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('evaluation_run_id', sa.Text(), nullable=False),
        sa.Column('purpose', sa.String(32), nullable=False),
        sa.Column('knowledge_freeze_sha256', sa.String(64), nullable=False),
        sa.Column('embedding_identity', postgresql.JSONB(), nullable=False),
        sa.Column('generator_identity', postgresql.JSONB()),
        sa.Column('prompt_version', sa.Text()), sa.Column('judge_model', sa.Text()),
        sa.Column('judge_prompt_version', sa.Text()), sa.Column('judge_run_id', sa.Text()),
        sa.Column('random_seed', sa.Integer(), nullable=False), sa.Column('code_version', sa.Text(), nullable=False),
        sa.UniqueConstraint('evaluation_run_id', name='evaluation_run_identifier'),
        sa.CheckConstraint("purpose IN ('retrieval','draft_latency','review')", name='evaluation_run_purpose'))
    op.create_table('evaluation_samples',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('evaluation_run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('evaluation_runs.id'), nullable=False),
        sa.Column('email_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('emails.id'), nullable=False),
        sa.Column('sample_source', sa.String(32), nullable=False), sa.Column('included', sa.Boolean(), nullable=False),
        sa.Column('exclusion_reason', sa.Text()), sa.UniqueConstraint('evaluation_run_id', 'email_id', name='evaluation_sample_once'),
        sa.CheckConstraint("sample_source IN ('real','synthetic_v2')", name='evaluation_sample_source'),
        sa.CheckConstraint("(included AND exclusion_reason IS NULL) OR (NOT included AND exclusion_reason IS NOT NULL)", name='evaluation_sample_inclusion_reason'))
    op.create_table('retrieval_observations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('evaluation_sample_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('evaluation_samples.id'), nullable=False),
        sa.Column('channel', sa.String(16), nullable=False), sa.Column('raw_rank', sa.Integer(), nullable=False),
        sa.Column('candidate_chunk_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('knowledge_chunks.id')),
        sa.Column('candidate_version', sa.Integer()), sa.Column('duration_ms', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False), sa.Column('failure_code', sa.Text()),
        sa.UniqueConstraint('evaluation_sample_id', 'channel', 'raw_rank', name='retrieval_observation_rank'),
        sa.CheckConstraint("channel IN ('keyword','vector','rrf')", name='retrieval_observation_channel'),
        sa.CheckConstraint("status IN ('succeeded','empty','failed','timed_out')", name='retrieval_observation_status'),
        sa.CheckConstraint('raw_rank >= 1', name='retrieval_observation_positive_rank'))
    op.create_table('retrieval_judgments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('retrieval_observation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('retrieval_observations.id'), nullable=False),
        sa.Column('blinded_rank', sa.Integer(), nullable=False), sa.Column('codex_label', sa.String(32), nullable=False),
        sa.Column('confidence', sa.Integer(), nullable=False), sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('audit_status', sa.String(32), server_default='pending', nullable=False), sa.Column('final_label', sa.String(32)),
        sa.UniqueConstraint('retrieval_observation_id', name='retrieval_judgment_observation_once'),
        sa.CheckConstraint("codex_label IN ('relevant','partially_relevant','not_relevant','no_answer')", name='retrieval_judgment_codex_label'),
        sa.CheckConstraint("final_label IS NULL OR final_label IN ('relevant','partially_relevant','not_relevant','no_answer')", name='retrieval_judgment_final_label'),
        sa.CheckConstraint("audit_status IN ('pending','confirmed','corrected','unable_to_judge')", name='retrieval_judgment_audit_status'))
    op.create_table('evaluation_executions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('evaluation_run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('evaluation_runs.id'), nullable=False),
        sa.Column('source_email_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('emails.id'), nullable=False),
        sa.Column('execution_email_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('emails.id'), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False), sa.Column('graph_thread_id', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False), sa.Column('failure_code', sa.Text()),
        sa.UniqueConstraint('evaluation_run_id', 'source_email_id', 'attempt', name='evaluation_execution_attempt'),
        sa.UniqueConstraint('execution_email_id', name='evaluation_execution_email_once'),
        sa.UniqueConstraint('graph_thread_id'), sa.CheckConstraint("status IN ('succeeded','failed','timed_out','archived')", name='evaluation_execution_status'),
        sa.CheckConstraint('attempt >= 1', name='evaluation_execution_positive_attempt'))
    op.create_table('evaluation_spans',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('evaluation_execution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('evaluation_executions.id'), nullable=False),
        sa.Column('stage', sa.Text(), nullable=False), sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=False), sa.Column('status', sa.String(16), nullable=False),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False),
        sa.UniqueConstraint('evaluation_execution_id', 'stage', name='evaluation_span_once'),
        sa.CheckConstraint("status IN ('succeeded','failed','skipped')", name='evaluation_span_status'),
        sa.CheckConstraint('duration_ms >= 0', name='evaluation_span_nonnegative_duration'),
        sa.CheckConstraint('retry_count >= 0', name='evaluation_span_nonnegative_retry'))
    for table in ('evaluation_samples', 'retrieval_observations', 'retrieval_judgments', 'evaluation_executions', 'evaluation_spans'):
        op.create_index(f'{table}_run_lookup', table, ['evaluation_run_id'] if table in ('evaluation_samples', 'evaluation_executions') else ['id'])


def downgrade():
    """显式回退时按引用逆序删除评估事实表。"""
    for table in ('evaluation_spans', 'evaluation_executions', 'retrieval_judgments', 'retrieval_observations', 'evaluation_samples'):
        op.drop_index(f'{table}_run_lookup', table_name=table)
        op.drop_table(table)
    op.drop_table('evaluation_runs')
