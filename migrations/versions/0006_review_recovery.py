"""B3 记录审核副作用是否已经完整补齐。"""
from alembic import op
import sqlalchemy as sa


revision = '0006_review_recovery'
down_revision = '0005_workflow_sync'
branch_labels = None
depends_on = None


def upgrade():
    """增加补偿完成时间，区分审核已保存与副作用已完成。"""
    op.add_column('reviews', sa.Column('result_applied_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    """显式回退 B3 补偿状态。"""
    op.drop_column('reviews', 'result_applied_at')
