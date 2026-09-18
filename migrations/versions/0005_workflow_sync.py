"""B1 IMAP 游标、任务游标审计与 LangGraph PostgreSQL checkpoint。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0005_workflow_sync'
down_revision = '0004_retrieval'
branch_labels = None
depends_on = None


def upgrade():
    """新增业务游标并建立当前 LangGraph PostgreSQL saver 所需结构。"""
    op.add_column('mail_sync_jobs', sa.Column('cursor_before', postgresql.JSONB(), nullable=True))
    op.add_column('mail_sync_jobs', sa.Column('cursor_after', postgresql.JSONB(), nullable=True))
    op.add_column('mail_messages', sa.Column('from_address', sa.Text(), nullable=True))
    op.create_table('mailbox_sync_states',
        sa.Column('mailbox_id', sa.Text(), nullable=False),
        sa.Column('uidvalidity', sa.Text(), nullable=False),
        sa.Column('last_committed_uid', sa.Integer(), nullable=False),
        sa.Column('history_sync_job_id', sa.UUID(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['history_sync_job_id'], ['mail_sync_jobs.id']),
        sa.PrimaryKeyConstraint('mailbox_id'))
    # Checkpointer 表由 Alembic 建立，运行时不自动修改应用业务迁移版本。
    op.execute("""CREATE TABLE IF NOT EXISTS checkpoint_migrations (v INTEGER PRIMARY KEY)""")
    op.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
        thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '', checkpoint_id TEXT NOT NULL,
        parent_checkpoint_id TEXT, type TEXT, checkpoint JSONB NOT NULL, metadata JSONB NOT NULL DEFAULT '{}',
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id))""")
    op.execute("""CREATE TABLE IF NOT EXISTS checkpoint_blobs (
        thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL,
        version TEXT NOT NULL, type TEXT NOT NULL, blob BYTEA,
        PRIMARY KEY (thread_id, checkpoint_ns, channel, version))""")
    op.execute("""CREATE TABLE IF NOT EXISTS checkpoint_writes (
        thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '', checkpoint_id TEXT NOT NULL,
        task_id TEXT NOT NULL, task_path TEXT NOT NULL DEFAULT '', idx INTEGER NOT NULL,
        channel TEXT NOT NULL, type TEXT, blob BYTEA NOT NULL,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx))""")
    op.create_index('checkpoints_thread_id_idx', 'checkpoints', ['thread_id'], if_not_exists=True)
    op.create_index('checkpoint_blobs_thread_id_idx', 'checkpoint_blobs', ['thread_id'], if_not_exists=True)
    op.create_index('checkpoint_writes_thread_id_idx', 'checkpoint_writes', ['thread_id'], if_not_exists=True)


def downgrade():
    """删除 B1 新增结构；checkpoint 数据仅在显式回退时移除。"""
    op.drop_index('checkpoint_writes_thread_id_idx', table_name='checkpoint_writes')
    op.drop_index('checkpoint_blobs_thread_id_idx', table_name='checkpoint_blobs')
    op.drop_index('checkpoints_thread_id_idx', table_name='checkpoints')
    op.drop_table('checkpoint_writes')
    op.drop_table('checkpoint_blobs')
    op.drop_table('checkpoints')
    op.drop_table('checkpoint_migrations')
    op.drop_table('mailbox_sync_states')
    op.drop_column('mail_messages', 'from_address')
    op.drop_column('mail_sync_jobs', 'cursor_after')
    op.drop_column('mail_sync_jobs', 'cursor_before')
