"""配置保护不能依赖数据库才能执行。"""
import json

import httpx
import pytest

from config import Settings, validate_test_database
from evals.harness.local_embedding import TeiEmbedder


@pytest.mark.parametrize('test_url', [
    'postgresql+psycopg://other:pass@localhost/email_agent',
    'postgresql+psycopg://other:pass@127.0.0.1/email_agent',
    'postgresql+psycopg://other:pass@localhost/not_a_test_database',
    'sqlite:///unit_test',
])
def test_business_database_never_used_as_test_database(test_url):
    """改用户名、端口或主机别名不能绕过业务库名称保护。"""
    with pytest.raises(ValueError, match='independent'):
        validate_test_database('postgresql+psycopg://owner:pass@postgres/email_agent', test_url)


def test_configured_model_reuses_identity_role_and_length_checks():
    """复用现有 TEI 校验并明确传递角色，长输入失败不会被静默截断。"""
    settings = Settings(_env_file=None, database_url='postgresql+psycopg://test:pass@localhost/unit_test')
    requests = []

    def handler(request):
        """提供受控响应，只验证协议边界，不代表真实模型推理。"""
        if request.url.path == '/info':
            return httpx.Response(200, json={'model_id': settings.embedding_model,
                                            'model_sha': settings.embedding_revision})
        payload = json.loads(request.content)
        requests.append(payload)
        if 'too-long' in payload['inputs'][0]:
            return httpx.Response(413)
        return httpx.Response(200, json=[[1.0] * settings.embedding_dimensions])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = TeiEmbedder(settings.local_model(), 'http://model.test', client=client)
        adapter.verify_identity()
        adapter.embed_queries(['question'])
        adapter.embed_documents(['document'])
        with pytest.raises(httpx.HTTPStatusError):
            adapter.embed_documents(['too-long'])
    assert requests[0]['inputs'] == [settings.embedding_query_prefix + 'question']
    assert requests[1]['inputs'] == [settings.embedding_document_prefix + 'document']
    assert all(request['truncate'] is False for request in requests)
