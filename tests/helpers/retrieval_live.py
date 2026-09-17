"""在独立测试库验证真实 Snowflake 查询嵌入、PostgreSQL 双路检索及来源版本。"""
import asyncio
import json
from pathlib import Path
import uuid

from config import Settings, validate_test_database
from db import Database
from models import KnowledgeChunk, KnowledgeDocument
from adapters.embedding import KnowledgeEmbedder
from services.knowledge import KnowledgeService
from services.retrieval import RetrievalService


async def main():
    """以本次唯一型号和标识隔离历史测试数据，不向业务知识库写入样本。"""
    baseline = Settings()
    test_url = baseline.test_database_url.get_secret_value()
    validate_test_database(baseline.database_url.get_secret_value(), test_url)
    marker = 'retrievallive' + uuid.uuid4().hex
    model = f'DS{uuid.uuid4().int % 1_000_000_000}+'
    root = Path('.codex-tmp') / ('a4-live-' + marker)
    root.mkdir(parents=True)
    root.joinpath('guide.md').write_text(
        f'# SMB troubleshooting\n\n{marker} applies to {model} on DSM 7.2.\n\n'
        'Check SMB service status before changing settings. Error 13 requires collecting logs first.\n',
        encoding='utf-8')
    settings = Settings(database_url=test_url, knowledge_root=root.resolve(),
                        knowledge_source_id='a4-live-' + marker, mailbox_id='a4-live-' + marker)
    database = Database(settings)
    try:
        await database.check_ready()
        product = await KnowledgeService(database).import_document(
            'guide.md', product_model=model, os_version='DSM 7.2', category='network')
        case_text = f'{marker} customer-safe reply wording for SMB error 13 on {model} DSM 7.2.'
        embedder = KnowledgeEmbedder(settings)
        try:
            embedder.verify_identity()
            case_vector = await asyncio.to_thread(embedder.embed_documents, [case_text])
        finally:
            embedder.close()
        async with database.session() as session:
            case_document = KnowledgeDocument(source_type='approved_case', source_ref='case:' + marker,
                title='Reviewed SMB case', version=1, status='active', content_hash=marker,
                index_version=settings.embedding_index_version, source_metadata={})
            session.add(case_document)
            await session.flush()
            session.add(KnowledgeChunk(document_id=case_document.id, chunk_index=0,
                content=case_text, embedding=case_vector[0],
                index_version=settings.embedding_index_version, product_model=model, os_version='DSM 7.2',
                category='network', section_path=['Reviewed case'], source_metadata={'fixture': marker}, token_count=20))
        result = await RetrievalService(database).retrieve(
            f'I have {model} DSM 7.2 SMB error 13 {marker}; what should I check?')
        product_ids = {item.document_id for item in result.sources['product_doc']}
        case_ids = {item.document_id for item in result.sources['approved_case']}
        assert product['id'] in product_ids
        assert str(case_document.id) in case_ids
        assert result.query_metadata == {'product_model': model, 'os_version': 'DSM 7.2'}
        assert result.evidence_assessed is False and result.has_reliable_evidence is False
        print(json.dumps({'database': 'independent_test', 'model': settings.embedding_model,
            'revision': settings.embedding_revision, 'rrf_k': result.rrf_k,
            'product_candidates': len(result.sources['product_doc']),
            'case_candidates': len(result.sources['approved_case']),
            'model_filter': result.query_metadata['product_model'],
            'version_filter': result.query_metadata['os_version']}))
    finally:
        await database.close()


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
