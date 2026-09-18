"""B2 固定边界验证垃圾、证据不足、引用越界与有限重试。"""
from types import SimpleNamespace

import pytest

from services.output_validation import OutputValidationError, validate_grounded_output
from services.retrieval import RetrievedChunk
from workflow.nodes import SafeDraftProcessor


def decision(**patch):
    """生成冻结 Schema 的基础合法决定。"""
    value = {'category': 'network', 'priority': 'normal', 'risks': [],
             'knowledge_status': 'sufficient', 'reason': 'product documentation',
             'missing_information': [], 'citations': [{'chunk_id': 'product-1', 'usage': 'fact'}],
             'reply_draft': 'Use the documented network settings.', 'requires_human_review': True}
    return value | patch


class FakeRetrieval:
    """返回按来源隔离的固定候选。"""

    def __init__(self, source_type='product_doc'):
        self.source_type = source_type
        self.calls = 0

    async def retrieve(self, query):
        self.calls += 1
        chunk = RetrievedChunk(chunk_id='product-1', document_id='doc-1', source_type=self.source_type,
            source_ref='fixture', version=1, title='Guide', content='Documented settings.',
            product_model=None, os_version=None, category='network', rank=1, rrf_score=1.0,
            keyword_rank=1, vector_rank=1)
        return SimpleNamespace(sources={'product_doc': [chunk]} if self.source_type == 'product_doc'
                               else {'approved_case': [chunk]})


class FakeGenerator:
    """按顺序返回测试决定，并记录有限调用次数。"""

    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    async def generate(self, messages):
        value = self.values[self.calls]
        self.calls += 1
        return value


@pytest.mark.asyncio
async def test_spam_archives_without_retrieval_or_generation():
    """垃圾邮件提前结束，不消耗检索和模型。"""
    retrieval, generator = FakeRetrieval(), FakeGenerator([decision()])
    result = await SafeDraftProcessor(retrieval, generator).process(
        {'subject': 'Limited offer', 'body_text': 'Buy now and unsubscribe.'})
    assert result['phase'] == 'archived'
    assert retrieval.calls == 0 and generator.calls == 0


@pytest.mark.asyncio
async def test_case_only_evidence_produces_restricted_manual_draft():
    """只有案例措辞时不得生成确定产品方案。"""
    result = await SafeDraftProcessor(FakeRetrieval('approved_case'), FakeGenerator([decision()])).process(
        {'subject': 'NAS issue', 'body_text': 'How do I configure it?'})
    assert result['decision']['knowledge_status'] == 'no_reliable_evidence'
    assert result['decision']['citations'] == []
    assert result['generation_attempts'] == 0
    assert result['query_rewrite_count'] == 1


@pytest.mark.asyncio
async def test_vip_sender_goes_directly_to_urgent_manual_review():
    """显式 VIP 地址不依赖模型分类，直接进入高关注人工路径。"""
    retrieval, generator = FakeRetrieval(), FakeGenerator([decision()])
    result = await SafeDraftProcessor(retrieval, generator, ('vip@example.test',)).process(
        {'from_address': 'VIP@example.test', 'subject': 'Need help', 'body_text': 'NAS offline'})
    assert result['priority'] == 'urgent' and result['risk'] == 'vip'
    assert retrieval.calls == 0 and generator.calls == 0


@pytest.mark.asyncio
async def test_invalid_generation_retries_only_to_fixed_limit():
    """越界引用连续失败后转人工，不能无限重新生成。"""
    invalid = decision(citations=[{'chunk_id': 'outside', 'usage': 'fact'}])
    generator = FakeGenerator([invalid, invalid])
    result = await SafeDraftProcessor(FakeRetrieval(), generator).process(
        {'subject': 'NAS issue', 'body_text': 'How do I configure it?'})
    assert result['risk'] == 'generation_validation_failed'
    assert result['generation_attempts'] == 2 and generator.calls == 2


def test_case_citation_cannot_support_product_fact():
    """格式合法也不能把案例片段标为产品事实依据。"""
    with pytest.raises(OutputValidationError, match='case_cannot_support_product_fact'):
        validate_grounded_output(decision(), [{'chunk_id': 'product-1', 'source_type': 'approved_case'}])
