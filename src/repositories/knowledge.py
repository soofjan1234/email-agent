"""知识持久化查询；服务层持有事务，锁与发布提交使用同一数据库会话。"""
import hashlib

from sqlalchemy import select, text

from models import KnowledgeDocument


async def lock_source(session, source_type, source_ref):
    """事务级来源锁串行化版本编号与重复发布；断线或回滚自动释放。"""
    digest = hashlib.blake2b(f'email-agent:knowledge:{source_type}:{source_ref}'.encode(), digest_size=8).digest()
    await session.execute(text('SELECT pg_advisory_xact_lock(:key)'),
                          {'key': int.from_bytes(digest, 'big', signed=True)})


async def document_versions(session, source_type, source_ref):
    """在来源锁内读取全部版本，旧引用永不被物理删除。"""
    return list((await session.scalars(select(KnowledgeDocument).where(
        KnowledgeDocument.source_type == source_type, KnowledgeDocument.source_ref == source_ref
    ).order_by(KnowledgeDocument.version.desc()))).all())


def active_chunks_statement():
    """统一暴露仅有效版本的片段查询，供 A4 添加检索排名。"""
    from models import KnowledgeChunk
    return select(KnowledgeChunk).join(KnowledgeDocument).where(KnowledgeDocument.status == 'active')
