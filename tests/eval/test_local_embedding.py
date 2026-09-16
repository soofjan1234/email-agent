"""本地模型接入必须区分输入角色并校验服务身份。"""
import json

import httpx
import pytest

from evals.harness.local_embedding import LocalModel, TeiEmbedder, main


def test_roles_and_anonymous_local_request():
    """查询和文档使用不同前缀，不向本地服务发送网关密钥。"""
    requests = []

    def handler(request):
        """返回固定身份和有效向量。"""
        if request.url.path == '/info':
            return httpx.Response(200, json={'model_id': 'demo', 'model_sha': 'abc'})
        requests.append(request)
        return httpx.Response(200, json=[[1, 0]])

    model = LocalModel('demo', 'abc', 2, 'search_query: ', 'search_document: ')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = TeiEmbedder(model, 'http://localhost:8080', client=client)
        embedder.verify_identity()
        embedder.embed_queries(['question'])
        embedder.embed_documents(['document'])
    assert [json.loads(r.content)['inputs'] for r in requests] == [
        ['search_query: question'], ['search_document: document']]
    assert all('authorization' not in r.headers for r in requests)
    assert all(json.loads(r.content)['truncate'] is False for r in requests)


def test_rejects_wrong_served_model():
    """服务端身份不匹配时拒绝评测。"""
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, json={'model_id': 'wrong', 'model_sha': 'abc'}))) as client:
        embedder = TeiEmbedder(LocalModel('demo', 'abc', 2), 'http://localhost', client=client)
        with pytest.raises(ValueError, match='identity'):
            embedder.verify_identity()


@pytest.mark.parametrize('vectors', [[[1, 0, 0]], [[0, 0]], [[1]], [[1, 0], [1, 0]]])
def test_rejects_invalid_vectors(vectors):
    """维度、非零及输入输出数量不符合契约时失败。"""
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, json=vectors))) as client:
        embedder = TeiEmbedder(LocalModel('demo', 'abc', 2), 'http://localhost', client=client)
        with pytest.raises(ValueError):
            embedder.embed_queries(['question'])


def test_cli_cannot_overwrite_freeze(tmp_path):
    """新入口即使指定冻结文件，也必须在发请求前拒绝覆盖。"""
    frozen = tmp_path / 'freeze.json'
    frozen.write_text('historical evidence', encoding='utf-8')
    with pytest.raises(SystemExit):
        main(['--model', 'snowflake', '--output', str(frozen)])
    assert frozen.read_text(encoding='utf-8') == 'historical evidence'


def test_cli_writes_failure_report_without_touching_dataset(tmp_path, monkeypatch):
    """身份失败也保留报告，且不会创建或修改数据集内的冻结文件。"""
    from evals.harness import local_embedding
    from evals.harness.dataset import DATASET_DIR

    original = (DATASET_DIR / 'freeze.json').read_bytes()

    def fail_identity(self):
        """模拟服务加载了错误模型。"""
        raise ValueError('identity mismatch')

    monkeypatch.setattr(local_embedding.TeiEmbedder, 'verify_identity', fail_identity)
    output = tmp_path / 'failed.json'
    assert main(['--model', 'snowflake', '--output', str(output)]) == 1
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['error_type'] == 'ValueError'
    assert report['dataset_sha256']['queries.jsonl']
    assert (DATASET_DIR / 'freeze.json').read_bytes() == original


def test_batches_fit_service_concurrency():
    """正式配置逐条串行输入，同时适配单槽服务并规避等长批次。"""
    sizes = []

    def handler(request):
        """模拟只接受单输入的服务。"""
        count = len(json.loads(request.content)['inputs'])
        sizes.append(count)
        return httpx.Response(429) if count > 1 else httpx.Response(200, json=[[1, 0]] * count)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        embedder = TeiEmbedder(LocalModel('demo', 'abc', 2), 'http://localhost', client=client)
        assert len(embedder.embed_queries(['q'] * 9)) == 9
    assert sizes == [1] * 9


def test_qwen_raw_control_records_empty_query_prefix(tmp_path, monkeypatch):
    """裸查询对照必须显式记录配置，便于复现实验。"""
    def fail_identity(self):
        """结束于网络边界之前，只验证命令行配置与报告。"""
        raise ValueError('identity unavailable')

    monkeypatch.setattr(TeiEmbedder, 'verify_identity', fail_identity)
    output = tmp_path / 'raw.json'
    assert main(['--model', 'qwen3', '--raw-query', '--output', str(output)]) == 1
    assert json.loads(output.read_text())['configuration']['query_prefix'] == ''


@pytest.mark.parametrize('batch_limit', [None, 4])
def test_qwen_tei_193_rejects_unvalidated_backend_batching(batch_limit):
    """已复现的等长批次缺陷不能被当成有效模型质量报告。"""
    model = LocalModel('Qwen/Qwen3-Embedding-0.6B', 'abc', 1024)
    info = {'model_id': model.model, 'model_sha': 'abc', 'version': '1.9.3',
            'max_concurrent_requests': batch_limit, 'max_client_batch_size': 1}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=info))) as client:
        embedder = TeiEmbedder(model, 'http://localhost', client=client)
        with pytest.raises(ValueError, match='concurrency=1'):
            embedder.verify_identity()


def test_qwen_tei_193_accepts_single_sequence_backend():
    model = LocalModel('Qwen/Qwen3-Embedding-0.6B', 'abc', 1024)
    info = {'model_id': model.model, 'model_sha': 'abc', 'version': '1.9.3',
            'max_concurrent_requests': 1, 'max_client_batch_size': 1}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=info))) as client:
        assert TeiEmbedder(model, 'http://localhost', client=client).verify_identity() == info
