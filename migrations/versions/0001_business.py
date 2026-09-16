"""A1 基础业务结构快照；向量列绑定本次显式开发候选配置。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector.sqlalchemy

from config import Settings

revision = '0001_business'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """首次迁移固定向量维度及编码身份，后续升级不会重写既有身份。"""
    settings = op.get_context().config.attributes.get('settings') or Settings()
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    # 按外键依赖顺序建立基础表。
    op.create_table('emails',
    sa.Column('client_request_id', sa.Text(), nullable=False),
    sa.Column('from_address', sa.Text(), nullable=False),
    sa.Column('subject', sa.Text(), nullable=False),
    sa.Column('body_text', sa.Text(), nullable=False),
    sa.Column('graph_thread_id', sa.Text(), nullable=True),
    sa.Column('workflow_generation', sa.Integer(), server_default='1', nullable=False),
    sa.Column('status', sa.String(length=64), server_default='received', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('workflow_generation >= 1', name='email_generation_positive'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('client_request_id'),
    sa.UniqueConstraint('graph_thread_id')
    )
    op.create_table('embedding_indexes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('index_version', sa.Text(), nullable=False),
    sa.Column('identity', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint('id = 1', name='embedding_single_identity'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('index_version')
    )
    op.create_table('historical_email_pairs',
    sa.Column('inbound_message_id', sa.Text(), nullable=False),
    sa.Column('outbound_message_id', sa.Text(), nullable=False),
    sa.Column('inbound_ref', sa.Text(), nullable=False),
    sa.Column('outbound_ref', sa.Text(), nullable=False),
    sa.Column('pairing_method', sa.Text(), server_default='header', nullable=False),
    sa.Column('pairing_confidence', sa.Float(), nullable=False),
    sa.Column('status', sa.Text(), server_default='needs_review', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("pairing_method = 'header'", name='pair_header_only'),
    sa.CheckConstraint("status IN ('paired','needs_review','rejected')", name='pair_status'),
    sa.CheckConstraint('pairing_confidence >= 0 AND pairing_confidence <= 1', name='pair_confidence'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('inbound_message_id'),
    sa.UniqueConstraint('outbound_message_id')
    )
    op.create_table('knowledge_documents',
    sa.Column('source_type', sa.String(length=32), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('source_ref', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), server_default='active', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source_type IN ('product_doc', 'approved_case')", name='document_source_type'),
    sa.CheckConstraint("status IN ('active', 'archived')", name='document_status'),
    sa.CheckConstraint('version >= 1', name='document_positive_version'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_type', 'source_ref', 'version', name='document_source_version')
    )
    op.create_table('audit_events',
    sa.Column('email_id', sa.UUID(), nullable=True),
    sa.Column('request_id', sa.Text(), nullable=True),
    sa.Column('graph_thread_id', sa.Text(), nullable=True),
    sa.Column('checkpoint_id', sa.Text(), nullable=True),
    sa.Column('event_type', sa.Text(), nullable=False),
    sa.Column('actor_type', sa.Text(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("actor_type IN ('system','agent','human')", name='audit_actor'),
    sa.ForeignKeyConstraint(['email_id'], ['emails.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('knowledge_chunks',
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.Vector(settings.embedding_dimensions), nullable=False),
    sa.Column('index_version', sa.Text(), nullable=False),
    sa.Column('product_model', sa.Text(), nullable=True),
    sa.Column('os_version', sa.Text(), nullable=True),
    sa.Column('category', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('chunk_index >= 0', name='chunk_nonnegative_index'),
    sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], ),
    sa.ForeignKeyConstraint(['index_version'], ['embedding_indexes.index_version'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'chunk_index', name='chunk_document_index')
    )
    op.create_table('reviews',
    sa.Column('email_id', sa.UUID(), nullable=False),
    sa.Column('graph_thread_id', sa.Text(), nullable=False),
    sa.Column('checkpoint_id', sa.Text(), nullable=False),
    sa.Column('review_request_id', sa.Text(), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('original_draft', sa.Text(), nullable=False),
    sa.Column('final_content', sa.Text(), nullable=True),
    sa.Column('citations', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('model_version', sa.Text(), nullable=False),
    sa.Column('prompt_version', sa.Text(), nullable=False),
    sa.Column('classification', sa.Text(), nullable=False),
    sa.Column('priority', sa.Text(), nullable=False),
    sa.Column('risk', sa.Text(), nullable=False),
    sa.Column('reviewer', sa.Text(), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("action IN ('approve','edit_and_approve','reject','manual_review')", name='review_action'),
    sa.ForeignKeyConstraint(['email_id'], ['emails.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('graph_thread_id', 'checkpoint_id', name='review_interrupt'),
    sa.UniqueConstraint('review_request_id')
    )
    op.create_table('case_candidates',
    sa.Column('email_pair_id', sa.UUID(), nullable=True),
    sa.Column('email_id', sa.UUID(), nullable=True),
    sa.Column('review_id', sa.UUID(), nullable=True),
    sa.Column('user_symptom', sa.Text(), nullable=False),
    sa.Column('applicability', sa.Text(), nullable=False),
    sa.Column('reply_template', sa.Text(), nullable=False),
    sa.Column('product_model', sa.Text(), nullable=True),
    sa.Column('os_version', sa.Text(), nullable=True),
    sa.Column('category', sa.Text(), nullable=True),
    sa.Column('risk_tags', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('redaction_result', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('review_comment', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default='candidate', nullable=False),
    sa.Column('published_document_id', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('candidate','reviewed','active','rejected','archived')", name='candidate_status'),
    sa.CheckConstraint('(email_pair_id IS NOT NULL AND email_id IS NULL AND review_id IS NULL) OR (email_pair_id IS NULL AND email_id IS NOT NULL AND review_id IS NOT NULL)', name='candidate_one_source'),
    sa.ForeignKeyConstraint(['email_id'], ['emails.id'], ),
    sa.ForeignKeyConstraint(['email_pair_id'], ['historical_email_pairs.id'], ),
    sa.ForeignKeyConstraint(['published_document_id'], ['knowledge_documents.id'], ),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email_pair_id'),
    sa.UniqueConstraint('review_id')
    )
    op.create_table('simulated_outbox',
    sa.Column('email_id', sa.UUID(), nullable=False),
    sa.Column('review_id', sa.UUID(), nullable=False),
    sa.Column('to_address', sa.Text(), nullable=False),
    sa.Column('subject', sa.Text(), nullable=False),
    sa.Column('body_text', sa.Text(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['email_id'], ['emails.id'], ),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('review_id')
    )


    identity_table = sa.table('embedding_indexes', sa.column('id', sa.Integer()),
                              sa.column('index_version', sa.Text()), sa.column('identity', postgresql.JSONB()))
    op.bulk_insert(identity_table, [{'id': 1, 'index_version': settings.embedding_index_version,
                                    'identity': settings.embedding_identity()}])


def downgrade():
    """显式降级删除业务表，保留可能被其他应用使用的 vector 扩展。"""
    # 按外键依赖的逆序删除表，避免先删除被引用对象。
    op.drop_table('simulated_outbox')
    op.drop_table('case_candidates')
    op.drop_table('reviews')
    op.drop_table('knowledge_chunks')
    op.drop_table('audit_events')
    op.drop_table('knowledge_documents')
    op.drop_table('historical_email_pairs')
    op.drop_table('embedding_indexes')
    op.drop_table('emails')

