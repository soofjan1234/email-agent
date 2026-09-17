"""A4 为知识片段建立 PostgreSQL 英文全文生成列和 GIN 索引。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004_retrieval'
down_revision = '0003_knowledge'
branch_labels = None
depends_on = None


def upgrade():
    """由数据库从 content 生成英文 tsvector，既有片段自动回填，不修改原始内容。"""
    op.add_column('knowledge_chunks', sa.Column('search_vector', postgresql.TSVECTOR(),
                  sa.Computed("to_tsvector('english', content)", persisted=True), nullable=True))
    op.create_index('knowledge_chunk_search_gin', 'knowledge_chunks', ['search_vector'],
                    unique=False, postgresql_using='gin')


def downgrade():
    """撤销派生索引和列，不删除知识片段或历史版本。"""
    op.drop_index('knowledge_chunk_search_gin', table_name='knowledge_chunks')
    op.drop_column('knowledge_chunks', 'search_vector')
