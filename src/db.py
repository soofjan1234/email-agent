"""异步事务入口：迁移独立执行，运行时核对数据库及模型配置。"""
from contextlib import asynccontextmanager

import numpy as np
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from config import Settings
from models import EmbeddingIndex, KnowledgeChunk


# A4 的知识索引结构必须已由独立迁移创建，运行进程不自动升级数据库。
SCHEMA_REVISION = '0008_evaluation_runs'


@event.listens_for(Session, 'before_flush')
def validate_embedding_writes(session, flush_context, instances):
    """提交前拒绝未验证会话、错误索引、非法维度和值。"""
    for record in session.new.union(session.dirty):
        if isinstance(record, EmbeddingIndex):
            raise ValueError('embedding identity can only be established by migrations')
        if isinstance(record, KnowledgeChunk):
            identity = session.info.get('embedding_identity')
            if not identity or record.index_version != identity['index_version']:
                raise ValueError('embedding identity mismatch')
            vector = np.asarray(record.embedding, dtype=np.float64)
            if (vector.shape != (identity['dimensions'],) or not np.isfinite(vector).all()
                    or np.linalg.norm(vector) == 0):
                raise ValueError('invalid embedding dimensions or values')


class Database:
    """API 和 worker 各自持有引擎；会话成功提交，异常完整回滚。"""

    def __init__(self, settings: Settings):
        """隐藏 SQL 参数，避免异常日志泄露正文和凭据。"""
        self.settings = settings
        self.engine = create_async_engine(settings.database_url.get_secret_value(),
                                          pool_pre_ping=True, hide_parameters=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def _verify_identity(self, session):
        """写会话读取数据库身份，禁止配置变化后继续混写。"""
        identity = await session.scalar(select(EmbeddingIndex.identity).where(EmbeddingIndex.id == 1))
        if identity != self.settings.embedding_identity():
            raise ValueError('embedding identity differs from migrated database')
        session.info['embedding_identity'] = identity

    @asynccontextmanager
    async def session(self):
        """先校验身份，再在单一事务中执行业务写入。"""
        async with self.sessions.begin() as session:
            await self._verify_identity(session)
            yield session

    async def check_ready(self):
        """验证迁移和扩展均已建立；不在多进程启动时迁移。"""
        async with self.session() as session:
            revision = await session.scalar(text('SELECT version_num FROM alembic_version'))
            extension = await session.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
            if revision != SCHEMA_REVISION or not extension:
                raise RuntimeError('database migration or vector extension is not ready')

    async def close(self):
        """关闭进程自己的连接池。"""
        await self.engine.dispose()
