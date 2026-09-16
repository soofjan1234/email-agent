"""扩展集的规模、路由、标注与场景隔离契约。"""
import hashlib
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from evals.harness.dataset import load_dataset
from evals.harness.local_embedding import LocalModel


ROOT = Path(__file__).resolve().parents[2] / 'evals' / 'embedding-v2'


def test_expanded_dataset_contract():
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    groups = {}
    query_ids = set()
    for split in ('dev', 'heldout'):
        folder = ROOT / split
        dataset = load_dataset(folder)
        chunks = {c.chunk_id: c for c in dataset.chunks}
        assert len(chunks) == len(dataset.chunks) >= 100
        assert len({c.content for c in dataset.chunks}) == len(chunks)
        assert all(c.language == 'en' for c in dataset.chunks)
        rows = [json.loads(line) for line in (folder / 'queries.jsonl').read_text(encoding='utf-8').splitlines()]
        groups[split] = {r['scenario_group'] for r in rows}
        assert len({r['query'] for r in rows}) == len(rows)
        assert {r['source_type'] for r in rows if not r['relevant_chunk_ids']} == {'product_doc', 'approved_case'}
        assert any(len(r['relevant_chunk_ids']) > 1 for r in rows)
        for row in rows:
            assert row['query_id'] not in query_ids
            query_ids.add(row['query_id'])
            assert row['language'] == 'en'
            assert row['split'] == split
            assert row['label_status'] == 'synthetic_author_reviewed'
            assert row['rationale']
            assert not set(row['relevant_chunk_ids']) & set(row['hard_negative_chunk_ids'])
            for chunk_id in row['relevant_chunk_ids'] + row['hard_negative_chunk_ids']:
                assert chunks[chunk_id].source_type == row['source_type']
            assert bool(row['relevant_chunk_ids']) != ('oos' in row['tags'])
        for name in ('chunks.jsonl', 'queries.jsonl'):
            assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == manifest['sha256'][f'{split}/{name}']
    assert not groups['dev'] & groups['heldout']
    assert len(query_ids) >= 100
    assert (ROOT / 'dev/chunks.jsonl').read_bytes() == (ROOT / 'heldout/chunks.jsonl').read_bytes()


def test_length_validation_uses_prefixed_inputs_and_rejects_overflow():
    spec = importlib.util.spec_from_file_location('expanded_comparison', ROOT / 'run_comparison.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dataset = load_dataset(ROOT / 'dev')
    dataset.chunks = dataset.chunks[:1]
    dataset.queries = dataset.queries[:1]
    observed = []

    def tokenize(request):
        body = json.loads(request.content)
        observed.append(body)
        # 文档刚好过线，查询加前缀后的服务分词结果超限。
        count = 8 if body['inputs'][0].startswith('document: ') else 9
        return httpx.Response(200, json=[[{'id': 1}] * count])

    with httpx.Client(transport=httpx.MockTransport(tokenize)) as client:
        model = LocalModel('fixture', 'revision', 3, 'query: ', 'document: ')
        with pytest.raises(ValueError, match='query token count'):
            module.validate_tokens(client, model, dataset, limit=8)
    assert observed[0] == {'inputs': ['document: ' + dataset.chunks[0].content], 'add_special_tokens': True}
    assert observed[1] == {'inputs': ['query: ' + dataset.queries[0].query], 'add_special_tokens': True}


def test_summary_rejects_runs_from_different_dataset(tmp_path):
    spec = importlib.util.spec_from_file_location('expanded_summary', ROOT / 'summarize.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'inputs.json').write_text(json.dumps({'dataset': {'sha256': {'queries': 'fixed'}}}))
    for number in range(1, 4):
        (tmp_path / f'snowflake-round-{number}.json').write_text(json.dumps({'dataset_sha256': {'queries': 'changed'}}))
    with pytest.raises(ValueError, match='different input hashes'):
        module.summarize(tmp_path)
