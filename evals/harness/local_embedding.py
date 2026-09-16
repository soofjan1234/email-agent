"""本地 TEI 模型评测，只输出独立报告，不修改冻结记录。"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import perf_counter

import httpx
import numpy as np

from evals.harness.dataset import DATASET_DIR, load_dataset
from evals.harness.embedder import EmbedderConfig, HttpEmbedder
from evals.harness.runner import evaluate_model

# 模型输入规则与 revision 一起版本化，不读取外部网关 .env。
MODEL_CONFIG = Path(__file__).resolve().parents[1] / 'embedding-models.json'
# 当前 CPU 对比统一单输入请求；服务并发也为一，规避 Qwen 等长批次缺陷。
CLIENT_BATCH_SIZE = 1


@dataclass(frozen=True)
class LocalModel:
    """模型身份、固定维度与查询/文档输入模板。"""
    model: str
    revision: str
    dimensions: int
    query_prefix: str = ''
    document_prefix: str = ''


class TeiEmbedder(HttpEmbedder):
    """通过 TEI 原生接口禁止截断，并记录各角色的编码耗时。"""

    def __init__(self, model: LocalModel, base_url: str, client=None):
        """使用独立无凭据客户端，保持与原运行器的配置兼容。"""
        super().__init__(EmbedderConfig(base_url, '', model.model, 180), client=client)
        self.model = model
        self.batches = []
        self.identity = None

    def verify_identity(self):
        """确认端点实际加载了指定权重 revision。"""
        response = self._client.get(self.config.base_url.rstrip('/') + '/info')
        response.raise_for_status()
        info = response.json()
        if info.get('model_id') != self.model.model or info.get('model_sha') != self.model.revision:
            raise ValueError('served model identity differs from configured model/revision')
        # 已在本机复现 1.9.3 Qwen 等长批次向量错误，评测只接受验证过的规避配置。
        if (self.model.model == 'Qwen/Qwen3-Embedding-0.6B' and info.get('version') == '1.9.3'
                and (info.get('max_concurrent_requests') != 1 or info.get('max_client_batch_size') != 1)):
            raise ValueError('Qwen TEI 1.9.3 CPU evaluation requires concurrency=1 and client_batch_size=1')
        self.identity = info
        return info

    def embed_documents(self, texts):
        """应用文档前缀，不修改原始夹具。"""
        return self._encode(texts, self.model.document_prefix, 'document')

    def embed_queries(self, texts):
        """应用查询前缀，角色不依赖请求先后顺序。"""
        return self._encode(texts, self.model.query_prefix, 'query')

    def embed(self, texts):
        """禁止模糊角色调用，避免使用错误的检索输入模板。"""
        raise ValueError('use embed_queries or embed_documents explicitly')

    def _encode(self, texts, prefix, role):
        """分小批请求，逐条验证返回向量并保存端到端批次耗时。"""
        vectors = []
        # 1. 串行单输入与服务限额一致，也避免上游等长批次掩码缺陷。
        for start in range(0, len(texts), CLIENT_BATCH_SIZE):
            inputs = [prefix + text for text in texts[start:start + CLIENT_BATCH_SIZE]]
            started = perf_counter()
            response = self._client.post(self.config.base_url.rstrip('/') + '/embed', json={
                'inputs': inputs, 'truncate': False, 'normalize': True})
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or len(rows) != len(inputs):
                raise ValueError('embedding count mismatch')
            # 2. 固定预期维度同时约束单批次与跨批次结果。
            batch = [np.asarray(row, dtype=np.float64) for row in rows]
            for vector in batch:
                if (vector.shape != (self.model.dimensions,) or not np.isfinite(vector).all()
                        or np.linalg.norm(vector) == 0):
                    raise ValueError('invalid embedding dimension or values')
            self.dimensions = self.model.dimensions
            vectors.extend(batch)
            self.batches.append({'role': role, 'texts': len(inputs),
                                 'seconds': perf_counter() - started})
        return vectors


def main(argv=None):
    """运行单模型冒烟评测，记录身份和输入哈希，成功与失败均保留报告。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--raw-query', action='store_true', help='Run the Qwen query-instruction ablation.')
    parser.add_argument('--base-url', default='http://127.0.0.1:18080')
    parser.add_argument('--dataset-dir', type=Path, default=DATASET_DIR)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    # 1. 禁止覆盖冻结记录或数据集原件，报告使用独立文件。
    if args.output.name in {'freeze.json', 'chunks.jsonl', 'queries.jsonl'} or args.output.exists():
        parser.error('output must be a new independent report file')
    configs = json.loads(MODEL_CONFIG.read_text(encoding='utf-8'))
    model = LocalModel(**configs[args.model])
    if args.raw_query:
        if args.model != 'qwen3':
            parser.error('--raw-query is only configured for the Qwen control experiment')
        model = replace(model, query_prefix='')
    embedder = TeiEmbedder(model, args.base_url)
    payload = {'experiment': 'docker-smoke-v1', 'configuration': asdict(model),
               'dataset_sha256': {name: hashlib.sha256((args.dataset_dir / name).read_bytes()).hexdigest()
                                  for name in ('chunks.jsonl', 'queries.jsonl')}}
    result = 1
    try:
        # 2. 先验证服务身份，再编码；冒烟耗时不宣称是稳态性能。
        payload['service'] = embedder.verify_identity()
        report = evaluate_model(load_dataset(args.dataset_dir), embedder)
        payload['report'] = asdict(report)
        result = 0 if report.passed else 1
    except (httpx.HTTPError, ValueError) as exc:
        payload['error_type'] = type(exc).__name__
        if isinstance(exc, httpx.HTTPStatusError):
            payload['http_status'] = exc.response.status_code
    finally:
        embedder.close()
    # 3. 不调用 write_freeze_record；使用排他创建防止覆盖已有报告。
    payload['batches'] = embedder.batches
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write('\n')
    print(json.dumps({'model': args.model, 'passed': result == 0, 'output': str(args.output)}))
    return result


if __name__ == '__main__':
    raise SystemExit(main())
