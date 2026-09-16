"""从十二份独立报告汇总质量、重复性、批次延迟和采样资源。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import numpy as np

MODELS = ('snowflake', 'nomic', 'bge-m3', 'qwen3')


def read(path):
    """只读取已保存原始报告，不调用模型或改变标签。"""
    return json.loads(path.read_text(encoding='utf-8'))


def memory_mib(value):
    """换算 Docker 带单位内存展示值；精度受原始展示精度限制。"""
    match = re.fullmatch(r'([\d.]+)(B|kB|MB|GB|KiB|MiB|GiB)', value.strip())
    if not match:
        raise ValueError('unrecognized Docker memory unit: ' + value)
    multiplier = {'B': 1, 'kB': 1000, 'MB': 1000**2, 'GB': 1000**3,
                  'KiB': 1024, 'MiB': 1024**2, 'GiB': 1024**3}[match[2]]
    return float(match[1]) * multiplier / 1024**2


def summarize(folder):
    """核对输入和服务身份后汇总；保留漏召回与首位错误的实际例子。"""
    inputs = read(folder / 'inputs.json')
    result = {'experiment': 'docker-expanded-v2', 'models': {}, 'dataset': inputs['dataset']}
    for alias in MODELS:
        rounds = [read(folder / f'{alias}-round-{i}.json') for i in range(1, 4)]
        for report in rounds:
            if report['dataset_sha256'] != inputs['dataset']['sha256']:
                raise ValueError('different input hashes: ' + alias)
            if report['configuration'] != inputs['models'][alias]:
                raise ValueError('different configured model: ' + alias)
            if report['service']['model_sha'] != report['configuration']['revision']:
                raise ValueError('different served revision: ' + alias)
        model = {'partitions': {}, 'timing': {}, 'tokens': read(folder / f'{alias}-tokens.json')}
        for split in ('dev', 'heldout'):
            first = rounds[0]['partitions'][split]
            rows = first['rows']
            scored = [r for r in rows if r['relevant_chunk_ids']]
            changes = [sum(a['ranked_ids'] != b['ranked_ids'] for a, b in zip(rows, r['partitions'][split]['rows'], strict=True)) for r in rounds[1:]]
            identifier = first['identifier_hits']
            model['partitions'][split] = {
                'summary': first['summary'], 'identifier_passed': len(identifier['passed']),
                'identifier_total': len(identifier['passed']) + len(identifier['failed']),
                'identifier_failed_queries': identifier['failed'],
                'threshold_passed': all(s['recall_at_3'] >= .8 for s in first['summary'].values()) and not identifier['failed'],
                'ranking_changes_vs_round1': changes,
                'complete_recall_queries': sum(set(r['relevant_chunk_ids']) <= set(r['ranked_ids']) for r in scored),
                'scored_queries': len(scored),
                'top3_incomplete': [r for r in scored if not set(r['relevant_chunk_ids']) <= set(r['ranked_ids'])],
                'top1_misses': [r for r in scored if r['ranked_ids'][0] not in r['relevant_chunk_ids']],
                'oos_rows': [r for r in rows if not r['relevant_chunk_ids']],
            }
        for role in ('document', 'query'):
            batches = [b for r in rounds for b in r['batches'] if b['role'] == role]
            batch_size = batches[0]['texts']
            if not all(b['texts'] == batch_size for b in batches):
                raise ValueError('mixed batch shape cannot be compared without stratification')
            times = [b['seconds'] for b in batches]
            model['timing'][role] = {'batches': len(batches), 'inputs_per_batch': batch_size,
                'p50_batch_ms': float(np.percentile(times, 50) * 1000),
                'p95_batch_ms': float(np.percentile(times, 95) * 1000),
                'inputs_per_second': batch_size * len(batches) / sum(times)}
        model['round_encoding_seconds'] = [sum(b['seconds'] for b in r['batches']) for r in rounds]
        samples = read(folder / f'{alias}-resources.json')
        good = [json.loads(s['raw']) for s in samples if s['exit_code'] == 0 and s['raw']]
        model['resources'] = {'samples': len(good), 'failed_samples': len(samples) - len(good),
            'sampled_max_memory_mib': max(memory_mib(s['MemUsage'].split('/')[0]) for s in good),
            'sampled_max_cpu_percent': max(float(s['CPUPerc'].rstrip('%')) for s in good),
            'method': 'docker stats during warm-up and evaluation; sampled maxima, not exact peaks'}
        result['models'][alias] = model
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    result = summarize(args.folder)
    with (args.folder / 'summary.json').open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    for alias, model in result['models'].items():
        print(json.dumps({'model': alias, 'heldout': {k: v for k, v in model['partitions']['heldout'].items()
                         if k not in {'top1_misses', 'oos_rows', 'top3_incomplete'}},
                         'top3_incomplete': [r['query_id'] for r in model['partitions']['heldout']['top3_incomplete']],
                         'timing': model['timing'], 'resources': model['resources'],
                         'round_seconds': model['round_encoding_seconds']}))


if __name__ == '__main__':
    main()
