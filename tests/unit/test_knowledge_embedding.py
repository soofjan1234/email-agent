"""业务模型边界验证真实 tokenizer 协议、模型身份及禁止截断。"""
import json

import httpx
import pytest

from adapters.embedding import KnowledgeEmbedder
from config import Settings


def settings():
    """不连接数据库，固定模型配置用于传输边界测试。"""
    return Settings(database_url='postgresql+psycopg://unused/unused', embedding_model='demo',
                    embedding_revision='abc', embedding_dimensions=2, embedding_document_prefix='doc: ')


def test_real_token_budget_includes_prefix_and_special_tokens():
    """/tokenize 必须收到与 /embed 相同的完整文本，并包含特殊 token。"""
    requests = []

    def handler(request):
        """只模拟 HTTP 服务返回，适配器及前缀处理走真实代码。"""
        requests.append(request)
        if request.url.path == '/info':
            return httpx.Response(200, json={'model_id': 'demo', 'model_sha': 'abc', 'max_input_length': 5})
        if request.url.path == '/tokenize':
            payload = json.loads(request.content)
            assert payload == {'inputs': ['doc: hello'], 'add_special_tokens': True}
            return httpx.Response(200, json=[[{'id': index} for index in range(5)]])
        assert json.loads(request.content) == {'inputs': ['doc: hello'], 'normalize': True, 'truncate': False}
        return httpx.Response(200, json=[[1, 0]])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = KnowledgeEmbedder(settings(), client)
        adapter.verify_identity()
        assert adapter.count_tokens('hello') == 5
        assert len(adapter.embed_documents(['hello'])) == 1
    assert [r.url.path for r in requests] == ['/info', '/tokenize', '/embed']
    assert all('authorization' not in r.headers for r in requests)


@pytest.mark.parametrize('info', [
    {'model_id': 'wrong', 'model_sha': 'abc', 'max_input_length': 5},
    {'model_id': 'demo', 'model_sha': 'wrong', 'max_input_length': 5},
    {'model_id': 'demo', 'model_sha': 'abc'},
])
def test_bad_model_identity_or_limit_is_rejected(info):
    """不能仅凭向量维度相同就接受模型或猜测输入预算。"""
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=info))) as client:
        with pytest.raises(ValueError):
            KnowledgeEmbedder(settings(), client).verify_identity()


def test_over_limit_never_calls_embed():
    """超预算在客户端拒绝，即使服务端默认自动截断也不会丢内容。"""
    def handler(request):
        """任意 /embed 调用都会使测试失败。"""
        assert request.url.path == '/tokenize'
        return httpx.Response(200, json=[[{'id': index} for index in range(6)]])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = KnowledgeEmbedder(settings(), client)
        adapter.max_input_length = 5
        with pytest.raises(ValueError, match='limit'):
            adapter.embed_documents(['hello'])
