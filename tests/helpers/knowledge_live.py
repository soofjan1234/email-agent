"""在独立测试库验证真实 TEI 长输入、案例发布和重试，不导入业务库。"""
import asyncio
import json
from pathlib import Path
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from config import Settings, validate_test_database
from db import Database
from main import create_app
from models import CaseCandidate, HistoricalEmailPair, KnowledgeChunk, KnowledgeDocument


async def main():
    """使用本次唯一来源，记录真实模型和数据库证据。"""
    baseline = Settings()
    url = baseline.test_database_url.get_secret_value()
    validate_test_database(baseline.database_url.get_secret_value(), url)
    key = str(uuid.uuid4())
    root = Path('.codex-tmp') / ('a3-live-' + key)
    root.mkdir(parents=True)
    root.joinpath('guide.md').write_text('# NAS-X guide\n\n## SMB\n\n' +
        'Check SMB service before changing settings. ' * 240 +
        '\n\n> FINAL WARNING: Never format disks. Contact alice@example.test.\n', encoding='utf-8')
    settings = Settings(database_url=url, knowledge_root=root.resolve(),
                        knowledge_source_id='a3-live-' + key, mailbox_id='a3-live-' + key)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        db = app.state.database
        async with db.session() as session:
            pair = HistoricalEmailPair(mailbox_id=settings.mailbox_id, inbound_message_id=key + '-in',
                outbound_message_id=key + '-out', inbound_ref='controlled:test-in', outbound_ref='controlled:test-out',
                pairing_confidence=1, status='needs_review')
            session.add(pair)
            await session.flush()
            candidate = CaseCandidate(email_pair_id=pair.id, user_symptom='SMB access failure',
                applicability='NAS-X', reply_template='Check SMB service.')
            session.add(candidate)
            await session.flush()
            pair_id, candidate_id = str(pair.id), str(candidate.id)
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', timeout=180) as client:
            product = await client.post('/api/v1/knowledge/import', json={'path': 'guide.md', 'product_model': 'NAS-X'})
            assert product.status_code == 200, product.text
            duplicate = await client.post('/api/v1/knowledge/import', json={'path': 'guide.md', 'product_model': 'NAS-X'})
            assert duplicate.json()['id'] == product.json()['id']
            assert (await client.post(f'/api/v1/case-pairs/{pair_id}/confirm',
                json={'action': 'confirm', 'reviewer': 'local-validation'})).status_code == 200
            reviewed = await client.post(f'/api/v1/case-candidates/{candidate_id}/review', json={
                'expected_revision': 1, 'action': 'approve', 'reviewer': 'local-validation',
                'user_symptom': 'SMB access failure reported by alice@example.test', 'applicability': 'NAS-X OS 2.1',
                'reply_template': 'Check SMB service status. ' * 220 + 'FINAL STEP: request diagnostic logs.',
                'fact_sources': ['test product guide'], 'product_model': 'NAS-X'})
            assert reviewed.status_code == 200, reviewed.text
            published = await client.post(f'/api/v1/case-candidates/{candidate_id}/publish',
                json={'expected_revision': reviewed.json()['revision']})
            assert published.status_code == 200, published.text
        summary = {}
        async with db.session() as session:
            for name, response, tail in (('product', product, 'FINAL WARNING'), ('case', published, 'FINAL STEP')):
                document_id = uuid.UUID(response.json()['id'])
                chunks = list((await session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))).all())
                assert tail in '\n'.join(chunk.content for chunk in chunks)
                assert all('alice@example.test' not in chunk.content for chunk in chunks)
                assert all(len(chunk.embedding) == 768 and chunk.token_count <= 512 for chunk in chunks)
                document = await session.get(KnowledgeDocument, document_id)
                assert document.status == 'active'
                summary[name] = {'chunks': len(chunks), 'max_tokens': max(chunk.token_count for chunk in chunks),
                                 'dimension': len(chunks[0].embedding), 'tail_preserved': True, 'redacted': True}
        print(json.dumps({'database': 'independent_test', 'model': settings.embedding_model,
                          'revision': settings.embedding_revision, 'results': summary}))


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
