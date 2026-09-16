"""向量身份和维度必须在业务写入边界明确验证。"""
import uuid

import pytest
from sqlalchemy import func, select

from db import Database
from models import KnowledgeChunk, KnowledgeDocument


@pytest.mark.parametrize('field,value', [
    ('embedding_model', 'other-model'), ('embedding_revision', 'other-revision'),
    ('embedding_dimensions', 3), ('embedding_query_prefix', 'other: '),
    ('embedding_document_prefix', 'other: '), ('embedding_index_version', 'other-index'),
])
async def test_wrong_configuration_rejected(database, field, value):
    """即使维度相同，模型、模板、revision 或索引改变也必须拒绝。"""
    wrong = Database(database.settings.model_copy(update={field: value}))
    try:
        with pytest.raises(ValueError, match='identity'):
            await wrong.check_ready()
        with pytest.raises(ValueError, match='identity'):
            async with wrong.session():
                pytest.fail('wrong configuration entered a writable session')
    finally:
        await wrong.close()


@pytest.mark.parametrize('vector', [[1.0], [0.0] * 768, [float('nan')] * 768])
async def test_invalid_vector_rejected_before_commit(database, vector):
    """错误维度、零向量和非有限值都不能污染有效知识。"""
    document_id = uuid.uuid4()
    with pytest.raises(ValueError, match='embedding'):
        async with database.session() as session:
            session.add(KnowledgeDocument(id=document_id, source_type='product_doc', title='test',
                                           source_ref=str(document_id), version=1))
            session.add(KnowledgeChunk(document_id=document_id, chunk_index=0, content='test',
                                       embedding=vector, index_version=database.settings.embedding_index_version))
    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id)) == 0


async def test_valid_vector_persists(database):
    """候选配置的向量可在真实 pgvector 列中往返。"""
    document_id = uuid.uuid4()
    async with database.session() as session:
        session.add(KnowledgeDocument(id=document_id, source_type='product_doc', title='test',
                                       source_ref=str(document_id), version=1))
        await session.flush()
        chunk = KnowledgeChunk(document_id=document_id, chunk_index=0, content='test',
                               embedding=[1.0] * 768, index_version=database.settings.embedding_index_version)
        session.add(chunk)
        await session.flush()
        chunk_id = chunk.id
    async with database.session() as session:
        stored = await session.get(KnowledgeChunk, chunk_id)
        assert len(stored.embedding) == 768
