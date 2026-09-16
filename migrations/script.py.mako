"""${message}。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector.sqlalchemy
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade():
    """应用本版本数据库结构变更。"""
    ${upgrades if upgrades else "pass"}


def downgrade():
    """仅由明确请求的回退命令撤销本版本。"""
    ${downgrades if downgrades else "pass"}
