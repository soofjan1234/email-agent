"""A4 用真实 PostgreSQL 验证关键词、向量、RRF、来源隔离和版本边界。"""
import uuid

import pytest
from sqlalchemy import text

from models import KnowledgeChunk, KnowledgeDocument
from services.retrieval import RetrievalError, RetrievalService


def vector(primary, secondary=0.0, dimensions=768):
    """构造非零固定维度向量，实际余弦检索仍由 PostgreSQL pgvector 执行。"""
    return [primary, secondary] + [0.0] * (dimensions - 2)


class FakeQueryEmbedding:
    """只替换不可避免的模型调用，保留数据库全文、向量和 RRF 查询。"""
    def __init__(self, dimensions=768):
        """记录查询角色输入，便于断言不把原始查询改写进数据库。"""
        self.dimensions = dimensions
        self.calls = []

    def verify_identity(self):
        """模拟已验证的 A3 索引身份。"""
        return {'model_id': 'test'}

    def embed_queries(self, texts):
        """返回与相关片段相近的查询向量。"""
        self.calls.extend(texts)
        return [vector(1.0, 0.0, self.dimensions) for _ in texts]

    def close(self):
        """测试替身没有外部连接。"""


async def add_document(database, source_type, title, content, embedding, *, model=None, os_version=None,
                       status='active', suffix=''):
    """以 A3 相同表结构建立独立检索语料，不调用发布服务或外部模型。"""
    async with database.session() as session:
        document = KnowledgeDocument(source_type=source_type, source_ref=f'{source_type}:{suffix}:{uuid.uuid4()}',
            title=title, version=1, status=status, content_hash=str(uuid.uuid4()).replace('-', ''),
            index_version=database.settings.embedding_index_version, source_metadata={})
        session.add(document)
        await session.flush()
        chunk = KnowledgeChunk(document_id=document.id, chunk_index=0, content=content, embedding=embedding,
            index_version=database.settings.embedding_index_version, product_model=model, os_version=os_version,
            category='network', section_path=[title], source_metadata={'fixture': suffix}, token_count=10)
        session.add(chunk)
        await session.flush()
        return document, chunk


async def test_dual_retrieval_isolates_sources_filters_explicit_identifiers_and_limits(database):
    """关键词与向量候选按来源 RRF 融合，明确 DS920+/DSM 7.2 时才加数据库过滤。"""
    marker = 'retrieval' + uuid.uuid4().hex
    model = f'DS{uuid.uuid4().int % 1_000_000_000}+'
    relevant_docs = []
    for index in range(4):
        _, chunk = await add_document(database, 'product_doc', f'Product {index}',
            f'{model} DSM 7.2 SMB error 13 {marker} troubleshooting step {index}', vector(1.0, index / 100),
            model=model, os_version='DSM 7.2', suffix=f'product-{index}')
        relevant_docs.append(chunk)
    _, wrong_model = await add_document(database, 'product_doc', 'Wrong model',
        f'{model} DSM 7.2 SMB error 13 {marker} troubleshooting', vector(1.0), model='DS423+', os_version='DSM 7.2',
        suffix='wrong-model')
    _, wrong_version = await add_document(database, 'product_doc', 'Wrong version',
        f'{model} DSM 7.2 SMB error 13 {marker} troubleshooting', vector(1.0), model=model, os_version='DSM 7.1',
        suffix='wrong-version')
    _, case = await add_document(database, 'approved_case', 'Case wording',
        f'{model} DSM 7.2 SMB error 13 {marker} reply wording', vector(1.0), model=model, os_version='DSM 7.2',
        suffix='case')
    _, archived = await add_document(database, 'product_doc', 'Archived',
        f'{model} DSM 7.2 SMB error 13 {marker} troubleshooting', vector(1.0), model=model, os_version='DSM 7.2',
        status='archived', suffix='archived')

    embedding = FakeQueryEmbedding(database.settings.embedding_dimensions)
    result = await RetrievalService(database, embedding_factory=lambda: embedding).retrieve(
        f'Need {model} DSM 7.2 SMB error 13 {marker} help')

    products = result.sources['product_doc']
    cases = result.sources['approved_case']
    product_ids = {item.chunk_id for item in products}
    assert len(products) == 3 and len(cases) == 1
    assert product_ids.issubset({str(chunk.id) for chunk in relevant_docs})
    assert str(wrong_model.id) not in product_ids
    assert str(wrong_version.id) not in product_ids
    assert str(archived.id) not in product_ids
    assert [item.source_type for item in products] == ['product_doc'] * 3
    assert [item.chunk_id for item in cases] == [str(case.id)]
    assert result.query_metadata == {'product_model': model, 'os_version': 'DSM 7.2'}
    assert result.rrf_k == 60 and result.evidence_assessed is False
    assert embedding.calls == [f'Need {model} DSM 7.2 SMB error 13 {marker} help']
    assert all(item.keyword_rank or item.vector_rank for item in products + cases)


async def test_unknown_identifiers_do_not_filter_and_case_only_hit_is_preserved(database):
    """没有明确型号/版本时不猜测过滤，案例命中不会被产品文档挤占。"""
    marker = 'retrieval' + uuid.uuid4().hex
    _, product = await add_document(database, 'product_doc', 'Product', f'{marker} SMB service guidance', vector(0.1, 1.0),
        model='DS920+', os_version='DSM 7.2', suffix='fallback-product')
    _, case = await add_document(database, 'approved_case', 'Case', f'{marker} SMB service wording', vector(1.0),
        model='DS423+', os_version='DSM 7.1', suffix='case-only')
    result = await RetrievalService(database, embedding_factory=lambda: FakeQueryEmbedding(
        database.settings.embedding_dimensions)).retrieve(marker)
    assert result.query_metadata == {'product_model': None, 'os_version': None}
    assert str(product.id) in {item.chunk_id for item in result.sources['product_doc']}
    assert str(case.id) in {item.chunk_id for item in result.sources['approved_case']}


async def test_no_answer_returns_candidates_without_claiming_reliable_evidence(database):
    """RRF 的相似候选不是充分证据，后续 Graph 必须另行评估。"""
    await add_document(database, 'product_doc', 'Unrelated', 'SMB service status', vector(1.0), suffix='unrelated')
    result = await RetrievalService(database, embedding_factory=lambda: FakeQueryEmbedding(
        database.settings.embedding_dimensions)).retrieve('How do I repair a broken coffee machine?')
    assert result.evidence_assessed is False
    assert result.has_reliable_evidence is False
    assert result.sources['product_doc']


async def test_embedding_identity_or_vector_shape_failure_is_explicit(database):
    """模型身份失败或异常向量绝不降级为关键词结果。"""
    class BadEmbedding(FakeQueryEmbedding):
        def verify_identity(self):
            raise ValueError('wrong model identity')

    with pytest.raises(RetrievalError) as error:
        await RetrievalService(database, embedding_factory=lambda: BadEmbedding()).retrieve('SMB')
    assert error.value.status == 503 and error.value.code == 'retrieval_embedding_failed'


async def test_full_text_generated_column_uses_gin_index(database):
    """全文通道基于迁移生成的英文 tsvector 与 GIN 索引，不在请求时重算文本列。"""
    async with database.session() as session:
        definition = await session.scalar(text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' "
            "AND indexname = 'knowledge_chunk_search_gin'"))
    assert definition and 'USING gin' in definition and 'search_vector' in definition

    class BadVector(FakeQueryEmbedding):
        def embed_queries(self, texts):
            return [[1.0]]

    with pytest.raises(RetrievalError) as error:
        await RetrievalService(database, embedding_factory=lambda: BadVector()).retrieve('SMB')
    assert error.value.status == 503 and error.value.code == 'retrieval_embedding_failed'
