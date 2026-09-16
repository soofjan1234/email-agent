"""顺序运行固定扩展集，保留分区质量、三轮时间及资源采样证据。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evals.harness.dataset import Dataset, load_dataset
from evals.harness.local_embedding import LocalModel, TeiEmbedder
from evals.harness.metrics import identifier_hits, summarize_scores
from evals.harness.retrieve import cosine_similarity
from evals.harness.runner import evaluate_model

# 同一短文本任务、固定资源和输入模板；不读取网关密钥或写历史冻结记录。
DATA = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:18080'
DOCKER = ['docker', '--context', 'desktop-linux']
COMPOSE = DOCKER + ['compose', '-f', str(ROOT / 'deploy/embedding/compose.yaml')]
CONTAINER = 'email-embedding-eval-embedding-1'
ROUNDS = 3


def save(path, value):
    """以新文件保存原始证据，禁止覆盖上一轮报告。"""
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def command(args, **kwargs):
    """捕获 Docker 输出，单次系统调用有明确超时。"""
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=60, cwd=ROOT, **kwargs)


class RecordingEmbedder(TeiEmbedder):
    """保存当轮查询向量用于导出候选相似度，不改变基础检索逻辑。"""
    def embed_queries(self, texts):
        vectors = super().embed_queries(texts)
        self.query_vectors = vectors
        return vectors


def validate_tokens(client, model, dataset, limit):
    """按实际服务分词验证每个完整输入，包括前缀与特殊 token。"""
    result = {}
    for role, texts, prefix in (
        ('document', [c.content for c in dataset.chunks], model.document_prefix),
        ('query', [q.query for q in dataset.queries], model.query_prefix),
    ):
        counts = []
        for start in range(0, len(texts)):
            inputs = [prefix + texts[start]]
            response = client.post(BASE + '/tokenize', json={'inputs': inputs, 'add_special_tokens': True})
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or len(rows) != len(inputs) or not all(isinstance(row, list) for row in rows):
                raise ValueError('unexpected tokenize response shape')
            counts.extend(len(row) for row in rows)
        if not counts or min(counts) <= 0 or max(counts) > limit:
            raise ValueError(f'{role} token count exceeds verified limit')
        result[role] = {'counts': counts, 'max_tokens': max(counts), 'inputs': len(counts), 'limit': limit}
    return result


def timing(batches):
    """批次形状一致，分角色计算客户端请求分位数和输入吞吐。"""
    result = {}
    for role in ('document', 'query'):
        selected = [b for b in batches if b['role'] == role]
        times = [b['seconds'] for b in selected]
        total = sum(times)
        count = sum(b['texts'] for b in selected)
        result[role] = {'batches': len(times), 'inputs': count, 'total_seconds': total,
                        'p50_batch_ms': float(np.percentile(times, 50) * 1000),
                        'p95_batch_ms': float(np.percentile(times, 95) * 1000),
                        'inputs_per_second': count / total}
    return result


def resource_sampler(stop, rows):
    """运行期间采样 Docker 统计；间隔含命令耗时，不能声称精确峰值。"""
    while not stop.is_set():
        sample = command(DOCKER + ['stats', '--no-stream', '--format', '{{json .}}', CONTAINER])
        rows.append({'at': datetime.now(timezone.utc).isoformat(), 'exit_code': sample.returncode,
                     'raw': sample.stdout.strip(), 'error': sample.stderr.strip()})
        stop.wait(1)


def evaluate_one(alias, config, folder, dataset, partitions, hashes):
    """同一容器顺序加载一个模型，验证身份后完成三轮评测。"""
    env = dict(os.environ, EMBED_MODEL_ID=config['model'], EMBED_MODEL_REVISION=config['revision'],
               EMBED_MAX_CONCURRENT_REQUESTS='1', EMBED_MAX_CLIENT_BATCH_SIZE='1')
    started = time.perf_counter()
    up = command(COMPOSE + ['up', '-d', '--force-recreate'], env=env)
    deployment = {'model': alias, 'configuration': config, 'startup_exit_code': up.returncode,
                  'startup_output': up.stdout + up.stderr}
    if up.returncode:
        save(folder / f'{alias}-deployment.json', deployment)
        raise RuntimeError('container startup command failed')
    with httpx.Client(timeout=30, trust_env=False) as client:
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            try:
                if client.get(BASE + '/health', timeout=3).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(3)
        else:
            raise RuntimeError('model readiness deadline exceeded')
        deployment['startup_wait_seconds'] = time.perf_counter() - started
        deployment['runtime'] = command(DOCKER + ['inspect', CONTAINER, '--format',
             '{{json .Image}} {{json .HostConfig.Memory}} {{json .HostConfig.NanoCpus}}']).stdout.strip()
        model = LocalModel(**config)
        embedder = RecordingEmbedder(model, BASE, client=client)
        deployment['identity'] = embedder.verify_identity()
        if (deployment['identity'].get('max_concurrent_requests') != 1
                or deployment['identity'].get('max_client_batch_size') != 1):
            raise ValueError('comparison requires single-input serial requests for every model')
        save(folder / f'{alias}-deployment.json', deployment)
        tokens = validate_tokens(client, model, dataset, deployment['identity']['max_input_length'])
        save(folder / f'{alias}-tokens.json', tokens)
        print(f'TOKENS {alias}: documents={tokens["document"]["max_tokens"]} queries={tokens["query"]["max_tokens"]}', flush=True)

        samples, stop = [], threading.Event()
        monitor = threading.Thread(target=resource_sampler, args=(stop, samples), daemon=True)
        monitor.start()
        try:
            for number in range(1, ROUNDS + 1):
                # 每轮同样预热，不将预热请求混入稳态批次样本。
                embedder.embed_documents([c.content for c in dataset.chunks[:4]])
                embedder.embed_queries([q.query for q in dataset.queries[:4]])
                warmup = embedder.batches[:]
                embedder.batches.clear()
                report = asdict(evaluate_model(dataset, embedder))
                chunks = {c.chunk_id: c for c in dataset.chunks}
                for row, query, vector in zip(report['rows'], dataset.queries, embedder.query_vectors, strict=True):
                    row['query'] = query.query
                    row['ranked_scores'] = [cosine_similarity(vector, chunks[c].embedding) for c in row['ranked_ids']]
                split_reports = {}
                for split, ids in partitions.items():
                    rows = [r for r in report['rows'] if r['query_id'] in ids]
                    split_reports[split] = {'summary': summarize_scores(rows),
                        'identifier_hits': identifier_hits([r for r in rows if 'identifier' in r['tags']]),
                        'rows': rows}
                payload = {'experiment': 'docker-expanded-v2', 'round': number, 'configuration': config,
                    'dataset_sha256': hashes, 'service': deployment['identity'], 'warmup_batches': warmup,
                    'batches': embedder.batches[:], 'timing': timing(embedder.batches),
                    'partitions': split_reports, 'combined_report': report}
                save(folder / f'{alias}-round-{number}.json', payload)
                print('ROUND ' + alias + ' ' + str(number) + ' ' + json.dumps({s: r['summary'] for s, r in split_reports.items()}), flush=True)
                embedder.batches.clear()
        finally:
            stop.set()
            monitor.join(timeout=65)
            save(folder / f'{alias}-resources.json', samples)
            logs = command(COMPOSE + ['logs', '--no-color', '--tail', '60'])
            (folder / f'{alias}-container.log').write_text(logs.stdout + logs.stderr, encoding='utf-8')


def main():
    """固定输入后启动所有候选，单模型失败保留证据并继续其他候选。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((DATA / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['sha256'].items():
        if hashlib.sha256((DATA / name).read_bytes()).hexdigest() != expected:
            raise ValueError('dataset differs from fixed manifest: ' + name)
    splits = {split: load_dataset(DATA / split) for split in ('dev', 'heldout')}
    if (DATA / 'dev/chunks.jsonl').read_bytes() != (DATA / 'heldout/chunks.jsonl').read_bytes():
        raise ValueError('partitions must share identical corpus')
    dataset = Dataset(splits['dev'].chunks, splits['dev'].queries + splits['heldout'].queries)
    partitions = {split: {q.query_id for q in data.queries} for split, data in splits.items()}
    configs = json.loads((ROOT / 'evals/embedding-models.json').read_text(encoding='utf-8'))
    save(args.output / 'inputs.json', {'dataset': manifest, 'models': configs, 'rounds': ROUNDS,
                                      'max_concurrent_requests': 1, 'max_client_batch_size': 1,
                                      'started_at': datetime.now(timezone.utc).isoformat()})
    failures = []
    try:
        for alias, config in configs.items():
            print('START ' + alias, flush=True)
            try:
                evaluate_one(alias, config, args.output, dataset, partitions, manifest['sha256'])
            except Exception as exc:
                failure = {'model': alias, 'error_type': type(exc).__name__, 'message': str(exc)}
                failures.append(failure)
                save(args.output / f'{alias}-error.json', failure)
                print('ERROR ' + json.dumps(failure), flush=True)
    finally:
        stopped = command(COMPOSE + ['stop'])
        save(args.output / 'completion.json', {'failures': failures, 'stop_exit_code': stopped.returncode,
            'state': command(DOCKER + ['inspect', CONTAINER, '--format', '{{json .State}}']).stdout.strip(),
            'finished_at': datetime.now(timezone.utc).isoformat()})
    print('FINISHED; experiment container stopped, model cache retained.', flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
