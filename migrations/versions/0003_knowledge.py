"""A3 知识版本指纹、章节来源及人工知识审核记录。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003_knowledge'
down_revision = '0002_history'
branch_labels = None
depends_on = None


def upgrade():
    """增量扩展现有表；旧记录原样保留，缺少指纹时重新生成完整版本。"""
    op.add_column('knowledge_documents', sa.Column('content_hash', sa.String(64)))
    op.add_column('knowledge_documents', sa.Column('index_version', sa.Text()))
    op.create_foreign_key('document_embedding_index', 'knowledge_documents', 'embedding_indexes',
                          ['index_version'], ['index_version'])
    op.add_column('knowledge_documents', sa.Column('source_metadata', postgresql.JSONB(),
                                                   nullable=False, server_default='{}'))
    op.add_column('knowledge_documents', sa.Column('raw_content', sa.Text()))
    op.add_column('knowledge_chunks', sa.Column('section_path', postgresql.JSONB(),
                                                nullable=False, server_default='[]'))
    op.add_column('knowledge_chunks', sa.Column('source_metadata', postgresql.JSONB(),
                                                nullable=False, server_default='{}'))
    op.add_column('knowledge_chunks', sa.Column('token_count', sa.Integer()))
    op.add_column('case_candidates', sa.Column('revision', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('case_candidates', sa.Column('reviewer', sa.Text()))
    op.add_column('case_candidates', sa.Column('fact_sources', postgresql.JSONB(),
                                               nullable=False, server_default='[]'))
    op.add_column('case_candidates', sa.Column('raw_review', postgresql.JSONB(),
                                               nullable=False, server_default='{}'))


def downgrade():
    """仅撤销 A3 新增字段，不删除 A1/A2 业务记录。"""
    for name in ('raw_review', 'fact_sources', 'reviewer', 'revision'):
        op.drop_column('case_candidates', name)
    for name in ('token_count', 'source_metadata', 'section_path'):
        op.drop_column('knowledge_chunks', name)
    op.drop_constraint('document_embedding_index', 'knowledge_documents', type_='foreignkey')
    for name in ('raw_content', 'source_metadata', 'index_version', 'content_hash'):
        op.drop_column('knowledge_documents', name)
