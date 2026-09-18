"""B2 邮件列表保存可从 checkpoint 重建的查询投影。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0007_workflow_projection'
down_revision = '0006_review_recovery'
branch_labels = None
depends_on = None


def upgrade():
    """增加列表筛选和草稿展示字段，不把它们作为 Graph 路由事实。"""
    op.add_column('emails', sa.Column('category', sa.Text(), nullable=True))
    op.add_column('emails', sa.Column('priority', sa.Text(), nullable=True))
    op.add_column('emails', sa.Column('risk', sa.Text(), nullable=True))
    op.add_column('emails', sa.Column('reply_draft', sa.Text(), nullable=True))
    op.add_column('emails', sa.Column('citations', postgresql.JSONB(), server_default='[]', nullable=False))


def downgrade():
    """显式移除 B2 查询投影。"""
    op.drop_column('emails', 'citations')
    op.drop_column('emails', 'reply_draft')
    op.drop_column('emails', 'risk')
    op.drop_column('emails', 'priority')
    op.drop_column('emails', 'category')
