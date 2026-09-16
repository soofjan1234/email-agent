"""比较同一输入独立与批量编码；只改请求批次，不改模型或模板。"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evals.harness.dataset import load_dataset
from evals.harness.retrieve import cosine_similarity

folder = ROOT / 'evals/embedding-v2/reports/docker-2026-09-15'
output = Path(sys.argv[1])
output.parent.mkdir(parents=True, exist_ok=True)
request_limit = int(sys.argv[2]) if len(sys.argv) > 2 else 1
assert request_limit in (1, 4)
assert not output.exists()
config = json.loads((ROOT / 'evals/embedding-models.json').read_text())['qwen3']
compose = ['docker', '--context', 'desktop-linux', 'compose', '-f', str(ROOT / 'deploy/embedding/compose.yaml')]
env = dict(os.environ, EMBED_MODEL_ID=config['model'], EMBED_MODEL_REVISION=config['revision'],
           EMBED_MAX_CONCURRENT_REQUESTS=str(request_limit), EMBED_MAX_CLIENT_BATCH_SIZE=str(request_limit))
dev = load_dataset(ROOT / 'evals/embedding-v2/dev')
heldout = load_dataset(ROOT / 'evals/embedding-v2/heldout')
records = []
try:
    subprocess.run(compose + ['up', '-d', '--force-recreate'], env=env, check=True, timeout=60)
    with httpx.Client(timeout=180, trust_env=False) as client:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                if client.get('http://127.0.0.1:18080/health', timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(2)
        identity = client.get('http://127.0.0.1:18080/info').json()
        assert identity['model_sha'] == config['revision']
        assert identity['max_concurrent_requests'] == request_limit
        assert identity['max_client_batch_size'] == request_limit

        def encode(texts):
            # 单输入模式按与正式适配器相同的方式串行，杜绝服务端等长合批。
            if request_limit == 1 and len(texts) > 1:
                return [encode([text])[0] for text in texts]
            response = client.post('http://127.0.0.1:18080/embed', json={'inputs': texts, 'truncate': False, 'normalize': True})
            response.raise_for_status()
            result = [np.asarray(v) for v in response.json()]
            assert len(result) == len(texts)
            assert all(v.shape == (1024,) and np.isfinite(v).all() for v in result)
            return result

        rejected_batch_status = None
        if request_limit == 1:
            rejected = client.post('http://127.0.0.1:18080/embed', json={
                'inputs': ['same input', 'same input'], 'truncate': False, 'normalize': True})
            rejected_batch_status = rejected.status_code
            assert 400 <= rejected.status_code < 500

        for role, items, targets in [
            ('document', [(c.chunk_id, c.content) for c in dev.chunks], ['pd-nfs-subnet', 'pd-encrypted-acl', 'pd-cache-read']),
            ('query', [(q.query_id, config['query_prefix'] + q.query) for q in dev.queries + heldout.queries],
             ['q-pd-nfs-subnet', 'q-pd-encrypted-acl', 'q-pd-cache-read']),
        ]:
            starts = sorted({next(i for i, item in enumerate(items) if item[0] == target) // 4 * 4 for target in targets})
            for start in starts:
                batch = items[start:start + 4]
                texts = [item[1] for item in batch]
                # 相同文本分别独立编码，再按原顺序和逆序组成四输入请求。
                singles = [encode([text])[0] for text in texts]
                together = encode(texts)
                reverse = encode(texts[::-1])[::-1]
                duplicates = encode([texts[0], texts[0]])
                row = {'role': role, 'ids': [item[0] for item in batch],
                    'input_sha256': [hashlib.sha256(text.encode()).hexdigest() for text in texts],
                    'single_vs_batch_cosine': [cosine_similarity(a, b) for a, b in zip(singles, together)],
                    'single_vs_reverse_cosine': [cosine_similarity(a, b) for a, b in zip(singles, reverse)],
                    'single_vs_duplicate_cosine': [cosine_similarity(singles[0], v) for v in duplicates],
                    'single_batch_matrix': [[cosine_similarity(a, b) for b in together] for a in singles],
                    'single_vectors': [v.tolist() for v in singles], 'batch_vectors': [v.tolist() for v in together]}
                records.append(row)
                print(json.dumps({k: v for k, v in row.items() if 'vectors' not in k}), flush=True)
        with output.open('x', encoding='utf-8') as handle:
            json.dump({'identity': identity, 'configuration': config, 'probes': records,
                       'rejected_raw_batch_status': rejected_batch_status}, handle, indent=2)
finally:
    subprocess.run(compose + ['stop'], timeout=60)

# 规避配置必须通过同一探针；原四序列配置保留为失败复现用途。
if request_limit == 1:
    assert all(min(row[key]) >= .999 for row in records for key in (
        'single_vs_batch_cosine', 'single_vs_reverse_cosine', 'single_vs_duplicate_cosine'))
