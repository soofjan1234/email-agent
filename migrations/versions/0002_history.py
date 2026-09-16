"""A2 历史任务、不可变快照、原文及一对一候选来源。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002_history'
down_revision = '0001_business'
branch_labels = None
depends_on = None


def upgrade():
    """保留 A1 数据，新增初始化状态并按邮箱限制配对唯一性。"""
    # 先建立任务、快照及邮件，再扩展配对的来源约束。
    op.create_table('mail_sync_jobs',
    sa.Column('mailbox_id', sa.Text(), nullable=False),
    sa.Column('mode', sa.Text(), nullable=False),
    sa.Column('sync_request_id', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='pending', nullable=False),
    sa.Column('stage', sa.Text(), server_default='snapshot', nullable=False),
    sa.Column('initialization_boundary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('scan_cursor', postgresql.JSONB(astext_type=sa.Text()), server_default='{"inbox":0,"sent":0}', nullable=False),
    sa.Column('scanned_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('added_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('skipped_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('failed_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('paired_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('candidate_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('unsupported_reasons', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('failure_type', sa.Text(), nullable=True),
    sa.Column('retryable', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mode IN ('historical_backfill','incremental')", name='sync_mode'),
    sa.CheckConstraint("stage IN ('snapshot','scanning','pairing','candidates','completed')", name='sync_stage'),
    sa.CheckConstraint("status IN ('pending','running','succeeded','failed')", name='sync_status'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mailbox_id', 'sync_request_id', name='sync_request_mailbox')
    )
    op.create_table('mail_sources',
    sa.Column('sync_job_id', sa.UUID(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('folder', sa.Text(), nullable=False),
    sa.Column('source_ref', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('raw_content', sa.LargeBinary(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("folder IN ('inbox','sent')", name='source_folder'),
    sa.ForeignKeyConstraint(['sync_job_id'], ['mail_sync_jobs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sync_job_id', 'ordinal', name='source_job_ordinal'),
    sa.UniqueConstraint('sync_job_id', 'source_ref', name='source_job_path')
    )
    op.create_table('mail_messages',
    sa.Column('mailbox_id', sa.Text(), nullable=False),
    sa.Column('sync_job_id', sa.UUID(), nullable=False),
    sa.Column('source_id', sa.UUID(), nullable=False),
    sa.Column('dedup_key', sa.String(length=64), nullable=False),
    sa.Column('folder', sa.Text(), nullable=False),
    sa.Column('message_id', sa.Text(), nullable=True),
    sa.Column('in_reply_to', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('references', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('subject', sa.Text(), nullable=False),
    sa.Column('body_text', sa.Text(), nullable=False),
    sa.Column('parse_error', sa.Text(), nullable=True),
    sa.Column('unsupported_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['mail_sources.id'], ),
    sa.ForeignKeyConstraint(['sync_job_id'], ['mail_sync_jobs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mailbox_id', 'dedup_key', name='message_mailbox_identity')
    )
    op.create_index('history_job_mailbox', 'mail_sync_jobs', ['mailbox_id'], unique=True, postgresql_where=sa.text("mode = 'historical_backfill'"))


    op.add_column('historical_email_pairs', sa.Column('mailbox_id', sa.Text(), server_default='local-mock', nullable=False))
    op.add_column('historical_email_pairs', sa.Column('sync_job_id', sa.UUID(), nullable=True))
    op.create_foreign_key('pair_sync_job', 'historical_email_pairs', 'mail_sync_jobs', ['sync_job_id'], ['id'])
    op.drop_constraint('historical_email_pairs_inbound_message_id_key', 'historical_email_pairs', type_='unique')
    op.drop_constraint('historical_email_pairs_outbound_message_id_key', 'historical_email_pairs', type_='unique')
    op.create_unique_constraint('pair_mailbox_inbound', 'historical_email_pairs', ['mailbox_id', 'inbound_message_id'])
    op.create_unique_constraint('pair_mailbox_outbound', 'historical_email_pairs', ['mailbox_id', 'outbound_message_id'])


def downgrade():
    """只允许显式回退；若旧全局唯一约束无法满足，事务会拒绝降级。"""
    op.create_unique_constraint('historical_email_pairs_inbound_message_id_key', 'historical_email_pairs', ['inbound_message_id'])
    op.create_unique_constraint('historical_email_pairs_outbound_message_id_key', 'historical_email_pairs', ['outbound_message_id'])
    op.drop_constraint('pair_mailbox_inbound', 'historical_email_pairs', type_='unique')
    op.drop_constraint('pair_mailbox_outbound', 'historical_email_pairs', type_='unique')
    op.drop_constraint('pair_sync_job', 'historical_email_pairs', type_='foreignkey')
    op.drop_column('historical_email_pairs', 'sync_job_id')
    op.drop_column('historical_email_pairs', 'mailbox_id')
    op.drop_table('mail_messages')
    op.drop_table('mail_sources')
    op.drop_table('mail_sync_jobs')
