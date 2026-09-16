"""A3 以真实 PostgreSQL 验证审核门槛、原子发布、重试与路径边界。"""
import asyncio
from pathlib import Path
import uuid

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select

from main import create_app
from models import CaseCandidate, HistoricalEmailPair, KnowledgeChunk, KnowledgeDocument
from services.knowledge import KnowledgeService, KnowledgeError


class FakeEmbedding:
    """仅替换不可避免的模型边界，记录实际传入模型的文本。"""
    def __init__(self, dimensions=768, fail_after=None):
        """用小输入预算强制覆盖长案例切分。"""
        self.dimensions, self.fail_after = dimensions, fail_after
        self.calls = []
        self.max_input_length = 180

    def verify_identity(self):
        """模拟已确认模型身份及 tokenizer 预算。"""
        return {'max_input_length': self.max_input_length}

    def count_tokens(self, value):
        """字符计数是确定性的测试 tokenizer，不替代生产模型计数。"""
        return len(value)

    def embed_documents(self, texts):
        """允许在部分输入成功后注入失败。"""
        result = []
        for value in texts:
            if self.fail_after is not None and len(self.calls) >= self.fail_after:
                raise ValueError('embedding failed with private upstream details')
            assert len(value) <= self.max_input_length
            self.calls.append(value)
            result.append([1.0] + [0.0] * (self.dimensions - 1))
        return result

    def close(self):
        """测试替身无外部资源。"""


async def seed_candidate(database):
    """创建与 A2 相同的确定配对与唯一候选，不写业务数据库。"""
    async with database.session() as session:
        pair = HistoricalEmailPair(mailbox_id=database.settings.mailbox_id,
            inbound_message_id=str(uuid.uuid4()), outbound_message_id=str(uuid.uuid4()),
            inbound_ref='mail-message:test-in', outbound_ref='mail-message:test-out',
            pairing_confidence=1, status='needs_review')
        session.add(pair)
        await session.flush()
        candidate = CaseCandidate(email_pair_id=pair.id, user_symptom='SMB error',
                                  applicability='NAS-X', reply_template='Check SMB.')
        session.add(candidate)
        await session.flush()
        return pair.id, candidate.id


def review_body(revision=1):
    """审核请求明确事实来源和适用范围，覆盖二次脱敏。"""
    return dict(expected_revision=revision, action='approve', reviewer='tester',
                user_symptom='SMB issue reported by alice@example.test', applicability='NAS-X OS 2.1',
                reply_template='Check SMB. ' * 70 + 'FINAL STEP', fact_sources=['manual:SMB section'],
                product_model='NAS-X', os_version='2.1', category='network',
                risk_tags=['read-only'], comment='Verified against product manual')


async def test_case_review_publish_retry_archive(database):
    """只有确认且审核的案例可以发布，重试复用版本，归档保留片段引用。"""
    pair_id, candidate_id = await seed_candidate(database)
    embedder = FakeEmbedding(database.settings.embedding_dimensions)
    service = KnowledgeService(database, embedding_factory=lambda: embedder)
    with pytest.raises(KnowledgeError) as error:
        await service.publish(candidate_id, 1)
    assert error.value.status == 409
    first = await service.confirm_pair(pair_id, 'confirm', 'tester')
    again = await service.confirm_pair(pair_id, 'confirm', 'tester')
    assert first['candidate_id'] == again['candidate_id'] == str(candidate_id)
    reviewed = await service.review(candidate_id, review_body())
    document = await service.publish(candidate_id, reviewed['revision'])
    count = len(embedder.calls)
    assert count > 1 and 'alice@example.test' not in ''.join(embedder.calls)
    assert 'FINAL STEP' in ''.join(embedder.calls)
    assert (await service.publish(candidate_id, reviewed['revision']))['id'] == document['id']
    assert len(embedder.calls) == count
    async with database.session() as session:
        chunks = list((await session.scalars(select(KnowledgeChunk).where(
            KnowledgeChunk.document_id == uuid.UUID(document['id'])))).all())
        ids = [c.id for c in chunks]
        assert all(c.source_metadata['candidate_id'] == str(candidate_id) for c in chunks)
        assert all(c.product_model == 'NAS-X' for c in chunks)
    await service.archive(candidate_id, reviewed['revision'], 'tester')
    async with database.session() as session:
        assert (await session.get(KnowledgeDocument, uuid.UUID(document['id']))).status == 'archived'
        assert all([await session.get(KnowledgeChunk, key) is not None for key in ids])


async def test_failed_update_keeps_previous_version_and_retry(database, tmp_path):
    """部分嵌入失败时旧版本仍有效，新版本和片段均不泄露。"""
    database.settings.knowledge_root = tmp_path
    path = tmp_path / 'guide.md'
    path.write_text('# Guide\n\nOriginal instructions.', encoding='utf-8')
    embedder = FakeEmbedding(database.settings.embedding_dimensions)
    service = KnowledgeService(database, embedding_factory=lambda: embedder)
    old = await service.import_document('guide.md', title='Guide', product_model='NAS-X')
    assert (await service.import_document('guide.md', title='Guide', product_model='NAS-X'))['id'] == old['id']
    calls = len(embedder.calls)
    path.write_text('# Guide\n\n' + 'New instructions. ' * 100, encoding='utf-8')
    embedder.fail_after = calls + 1
    with pytest.raises(KnowledgeError) as error:
        await service.import_document('guide.md', title='Guide', product_model='NAS-X')
    assert error.value.status == 503
    async with database.session() as session:
        docs = list((await session.scalars(select(KnowledgeDocument).where(
            KnowledgeDocument.source_ref == old['source_ref']))).all())
        assert len(docs) == 1 and docs[0].status == 'active'
    embedder.fail_after = None
    new = await service.import_document('guide.md', title='Guide', product_model='NAS-X')
    assert new['version'] == 2 and new['id'] != old['id']
    async with database.session() as session:
        assert (await session.get(KnowledgeDocument, uuid.UUID(old['id']))).status == 'archived'
        assert await session.scalar(select(KnowledgeChunk.id).where(
            KnowledgeChunk.document_id == uuid.UUID(old['id'])))


@pytest.mark.parametrize('path', ['../outside.md', '/etc/passwd', 'C:\\private.md',
                                  '..\\outside.md', 'guide.md:stream', '.env'])
async def test_import_rejects_untrusted_paths(database, tmp_path, path):
    """跨平台路径、备用数据流及非 Markdown 文件不能作为导入入口。"""
    database.settings.knowledge_root = tmp_path
    with pytest.raises(KnowledgeError) as error:
        await KnowledgeService(database).import_document(path)
    assert error.value.status == 400


async def test_import_rejects_outside_link(database, tmp_path):
    """最终解析位置必须仍在可信目录内。"""
    root = tmp_path / 'trusted'
    root.mkdir()
    outside = tmp_path / 'outside.md'
    outside.write_text('private', encoding='utf-8')
    try:
        (root / 'link.md').symlink_to(outside)
    except OSError:
        pytest.skip('OS does not permit file symlinks')
    database.settings.knowledge_root = root
    with pytest.raises(KnowledgeError):
        await KnowledgeService(database).import_document('link.md')


async def test_concurrent_import_publishes_once(database, tmp_path):
    """同来源并发导入复用完整版本，不重复嵌入。"""
    database.settings.knowledge_root = tmp_path
    (tmp_path / 'guide.md').write_text('# Guide\n\nCheck SMB.', encoding='utf-8')
    embedder = FakeEmbedding(database.settings.embedding_dimensions)
    service = KnowledgeService(database, embedding_factory=lambda: embedder)
    results = await asyncio.gather(*(service.import_document('guide.md') for _ in range(2)))
    assert results[0]['id'] == results[1]['id']
    assert len(embedder.calls) == 1


async def test_api_state_guards_and_safe_errors(database):
    """接口拒绝未确认审核、过期修改和非法路径，不返回受控原文。"""
    pair_id, candidate_id = await seed_candidate(database)
    app = create_app(database.settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            prefix = f'/api/v1/case-candidates/{candidate_id}'
            assert (await client.post(prefix + '/review', json=review_body())).status_code == 409
            assert (await client.post(f'/api/v1/case-pairs/{pair_id}/confirm',
                                     json={'action': 'confirm', 'reviewer': 'tester'})).status_code == 200
            response = await client.post(prefix + '/review', json=review_body())
            assert response.status_code == 200, response.text
            assert 'alice@example.test' not in response.text and 'raw_review' not in response.text
            assert (await client.post(prefix + '/review', json=review_body())).status_code == 409
            assert (await client.get('/api/v1/case-candidates?status=reviewed')).json()['total'] == 1
            assert (await client.get('/api/v1/case-candidates?page=0')).status_code == 400
            response = await client.post('/api/v1/knowledge/import', json={'path': '../.env'})
            assert response.status_code == 400 and response.json()['request_id']
            assert (await client.get(f'/api/v1/case-candidates/{uuid.uuid4()}')).status_code == 404


async def test_revised_case_publishes_new_version_and_old_reference_survives(database):
    """已发布案例修改须重新审核；新版本失败时保持旧知识有效。"""
    pair_id, candidate_id = await seed_candidate(database)
    embedder = FakeEmbedding(database.settings.embedding_dimensions)
    service = KnowledgeService(database, embedding_factory=lambda: embedder)
    await service.confirm_pair(pair_id, 'confirm', 'tester')
    reviewed = await service.review(candidate_id, review_body())
    old = await service.publish(candidate_id, reviewed['revision'])
    payload = review_body(reviewed['revision'])
    payload['reply_template'] = 'A corrected answer.'
    revised = await service.review(candidate_id, payload)
    embedder.fail_after = len(embedder.calls)
    with pytest.raises(KnowledgeError):
        await service.publish(candidate_id, revised['revision'])
    async with database.session() as session:
        assert (await session.get(KnowledgeDocument, uuid.UUID(old['id']))).status == 'active'
        assert (await session.get(CaseCandidate, candidate_id)).status == 'reviewed'
    embedder.fail_after = None
    new = await service.publish(candidate_id, revised['revision'])
    assert new['version'] == 2
    async with database.session() as session:
        old_row = await session.get(KnowledgeDocument, uuid.UUID(old['id']))
        assert old_row.status == 'archived'
        assert 'alice@example.test' in old_row.raw_content
        assert 'A corrected answer.' not in old_row.raw_content


async def test_reject_cannot_leave_unreviewed_published_case_active(database):
    """已有发布版本的案例不能通过配对拒绝留下失去管理入口的有效知识。"""
    pair_id, candidate_id = await seed_candidate(database)
    service = KnowledgeService(database, embedding_factory=lambda: FakeEmbedding(database.settings.embedding_dimensions))
    await service.confirm_pair(pair_id, 'confirm', 'tester')
    reviewed = await service.review(candidate_id, review_body())
    await service.publish(candidate_id, reviewed['revision'])
    await service.review(candidate_id, review_body(reviewed['revision']))
    with pytest.raises(KnowledgeError) as error:
        await service.confirm_pair(pair_id, 'reject', 'tester')
    assert error.value.status == 409


@pytest.mark.parametrize('sources', [[], [''], ['   ']])
async def test_blank_fact_sources_never_count_as_review(database, sources):
    """空白字符串不能绕过事实来源必填要求。"""
    pair_id, candidate_id = await seed_candidate(database)
    service = KnowledgeService(database)
    await service.confirm_pair(pair_id, 'confirm', 'tester')
    payload = review_body()
    payload['fact_sources'] = sources
    with pytest.raises(KnowledgeError) as error:
        await service.review(candidate_id, payload)
    assert error.value.status == 400


async def test_commit_failure_rolls_back_written_chunks(database, tmp_path):
    """真实事务在写完片段后提交失败，重试不得留下重复版本或部分片段。"""
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    database.settings.knowledge_root = tmp_path
    (tmp_path / 'guide.md').write_text('# Guide\n\nCheck SMB.', encoding='utf-8')
    service = KnowledgeService(database, embedding_factory=lambda: FakeEmbedding(database.settings.embedding_dimensions))

    def fail_commit(session):
        """只拦截本次测试知识来源的事务提交。"""
        if any(isinstance(record, KnowledgeDocument) and record.source_ref.startswith(
                database.settings.knowledge_source_id + ':') for record in session.identity_map.values()):
            raise RuntimeError('test commit failure')

    event.listen(Session, 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError, match='test commit failure'):
            await service.import_document('guide.md')
    finally:
        event.remove(Session, 'before_commit', fail_commit)
    async with database.session() as session:
        assert not list((await session.scalars(select(KnowledgeDocument).where(
            KnowledgeDocument.source_ref == database.settings.knowledge_source_id + ':guide.md'))).all())
    assert (await service.import_document('guide.md'))['version'] == 1


async def test_product_import_keeps_blockquote_and_redacts_before_embedding(database, tmp_path):
    """产品风险提示中的引用段落不可当邮件引用链丢弃，敏感值不进入模型。"""
    database.settings.knowledge_root = tmp_path
    fixture = Path(__file__).resolve().parents[1] / 'fixtures/knowledge/product.md'
    (tmp_path / 'guide.md').write_text(fixture.read_text(encoding='utf-8') + '\n> Never format disks.\n', encoding='utf-8')
    embedder = FakeEmbedding(database.settings.embedding_dimensions)
    document = await KnowledgeService(database, embedding_factory=lambda: embedder).import_document('guide.md')
    texts = '\n'.join(embedder.calls)
    assert 'Never format disks.' in texts
    assert 'alice@example.test' not in texts and 'SNABCDEF1234' not in texts
    async with database.session() as session:
        assert 'alice@example.test' in (await session.get(KnowledgeDocument, uuid.UUID(document['id']))).raw_content


async def test_api_embedding_failure_is_safe_and_retry_works(database, tmp_path):
    """接口可在运行期间导入，模型失败只返回固定错误，重试完成同一来源。"""
    database.settings.knowledge_root = tmp_path
    (tmp_path / 'guide.md').write_text('# Guide\n\nCheck SMB.', encoding='utf-8')
    app = create_app(database.settings)
    embedder = FakeEmbedding(database.settings.embedding_dimensions, fail_after=0)
    app.state.embedding_factory = lambda: embedder
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/v1/knowledge/import', json={'path': 'guide.md'})
            assert response.status_code == 503
            assert 'private' not in response.text and response.json()['request_id']
            embedder.fail_after = None
            response = await client.post('/api/v1/knowledge/import', json={'path': 'guide.md'})
            assert response.status_code == 200 and response.json()['version'] == 1


async def test_metadata_revision_reuses_same_text_embeddings(database, tmp_path):
    """仅适用元数据变化产生新版本，但相同内容和索引身份不重复嵌入。"""
    database.settings.knowledge_root = tmp_path
    (tmp_path / 'guide.md').write_text('# Guide\n\nCheck SMB.', encoding='utf-8')
    embedder = FakeEmbedding(database.settings.embedding_dimensions)
    service = KnowledgeService(database, embedding_factory=lambda: embedder)
    first = await service.import_document('guide.md', product_model='NAS-X')
    calls = len(embedder.calls)
    second = await service.import_document('guide.md', product_model='NAS-Y')
    assert second['version'] == first['version'] + 1
    assert len(embedder.calls) == calls


async def test_active_query_excludes_candidate_and_archived(database):
    """A4 的统一基础查询只允许有效文档，归档不删除片段本身。"""
    from repositories.knowledge import active_chunks_statement

    pair_id, candidate_id = await seed_candidate(database)
    service = KnowledgeService(database, embedding_factory=lambda: FakeEmbedding(database.settings.embedding_dimensions))
    async with database.session() as session:
        assert (await session.get(CaseCandidate, candidate_id)).published_document_id is None
    await service.confirm_pair(pair_id, 'confirm', 'tester')
    reviewed = await service.review(candidate_id, review_body())
    document = await service.publish(candidate_id, reviewed['revision'])
    statement = active_chunks_statement().where(KnowledgeChunk.document_id == uuid.UUID(document['id']))
    async with database.session() as session:
        assert list((await session.scalars(statement)).all())
    await service.archive(candidate_id, reviewed['revision'], 'tester')
    async with database.session() as session:
        assert not list((await session.scalars(statement)).all())
