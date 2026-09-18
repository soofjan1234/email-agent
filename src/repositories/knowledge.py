"""知识持久化查询；服务层持有事务，锁与发布提交使用同一数据库会话。"""
import hashlib

from sqlalchemy import func, select, text

from models import KnowledgeChunk, KnowledgeDocument


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
    return select(KnowledgeChunk).join(KnowledgeDocument).where(KnowledgeDocument.status == 'active')


def _active_source_filters(source_type, index_version, product_model, os_version):
    """所有通道共享有效版本、索引身份及明确适用范围过滤，避免两路结果不一致。"""
    filters = [KnowledgeDocument.status == 'active', KnowledgeDocument.source_type == source_type,
               KnowledgeChunk.index_version == index_version]
    if product_model is not None:
        filters.append(KnowledgeChunk.product_model == product_model)
    if os_version is not None:
        filters.append(KnowledgeChunk.os_version == os_version)
    return filters


async def keyword_search(session, source_type, normalized_tokens, index_version, product_model, os_version, limit):
    """用 PostgreSQL english 全文检索返回每个来源的独立排名，不跨来源补位。"""
    # 受控上限避免长邮件的分词结果构造过深 SQL 表达式；向量通道仍使用完整原查询。
    normalized_tokens = normalized_tokens[:16]
    if not normalized_tokens:
        return []
    # 自然语言中常有文档不存在的补充词；逐词 OR 保留标识召回，再交给 RRF 处理排序。
    tsquery = func.websearch_to_tsquery('english', normalized_tokens[0])
    for token in normalized_tokens[1:]:
        tsquery = tsquery.op('||')(func.websearch_to_tsquery('english', token))
    rank = func.ts_rank_cd(KnowledgeChunk.search_vector, tsquery).label('score')
    statement = select(KnowledgeChunk, KnowledgeDocument, rank).join(KnowledgeDocument).where(
        *_active_source_filters(source_type, index_version, product_model, os_version),
        KnowledgeChunk.search_vector.op('@@')(tsquery)
    ).order_by(rank.desc(), KnowledgeChunk.id).limit(limit)
    return list((await session.execute(statement)).all())


async def vector_search(session, source_type, query_vector, index_version, product_model, os_version, limit):
    """用 pgvector 精确余弦距离返回每个来源的独立排名，维度由写入边界和服务层双重检查。"""
    distance = KnowledgeChunk.embedding.cosine_distance(query_vector).label('distance')
    statement = select(KnowledgeChunk, KnowledgeDocument, distance).join(KnowledgeDocument).where(
        *_active_source_filters(source_type, index_version, product_model, os_version)
    ).order_by(distance, KnowledgeChunk.id).limit(limit)
    return list((await session.execute(statement)).all())
