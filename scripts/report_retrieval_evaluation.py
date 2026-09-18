"""生成脱敏检索评估报告；标注或抽检不完整时绝不输出 Recall/MRR。"""
import argparse
import asyncio
import json
from math import ceil
from pathlib import Path
import statistics
import sys

from sqlalchemy import select

from config import Settings
from db import Database
from models import EvaluationRun, EvaluationSample, RetrievalJudgment, RetrievalObservation


def percentile(values, ratio):
    """按最近秩返回延迟分位数；空集合保持空而非伪造零耗时。"""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[ceil(len(ordered) * ratio) - 1]


def channel_summary(rows):
    """汇总一个来源口径下的通道观测，不包含邮件、片段或客户内容。"""
    summary = {}
    for channel in ('keyword', 'vector', 'rrf'):
        items = [row for row in rows if row['channel'] == channel]
        durations = [row['duration_ms'] for row in items]
        summary[channel] = {'observation_count': len(items),
            'succeeded_count': sum(row['status'] == 'succeeded' for row in items),
            'empty_count': sum(row['status'] == 'empty' for row in items),
            'failed_count': sum(row['status'] == 'failed' for row in items),
            'timed_out_count': sum(row['status'] == 'timed_out' for row in items),
            'p50_ms': percentile(durations, 0.5), 'p95_ms': percentile(durations, 0.95),
            'max_ms': max(durations) if durations else None}
    return summary


async def build_report(settings, evaluation_run_id):
    """读取评估事实并依据抽检完成度决定是否允许输出质量指标。"""
    database = Database(settings)
    try:
        await database.check_ready()
        async with database.session() as session:
            run = await session.scalar(select(EvaluationRun).where(EvaluationRun.evaluation_run_id == evaluation_run_id))
            if run is None:
                raise ValueError('unknown_evaluation_run')
            values = (await session.execute(select(EvaluationSample, RetrievalObservation, RetrievalJudgment).
                select_from(EvaluationSample).join(RetrievalObservation,
                RetrievalObservation.evaluation_sample_id == EvaluationSample.id).outerjoin(RetrievalJudgment,
                RetrievalJudgment.retrieval_observation_id == RetrievalObservation.id).where(
                EvaluationSample.evaluation_run_id == run.id))).all()
        rows = [{'sample_source': sample.sample_source, 'channel': observation.channel, 'status': observation.status,
                 'duration_ms': observation.duration_ms, 'sample_id': str(sample.id),
                 'rank': observation.raw_rank, 'label': (judgment.final_label if judgment and judgment.audit_status == 'corrected'
                 else judgment.codex_label if judgment else None), 'audit_status': judgment.audit_status if judgment else None}
                for sample, observation, judgment in values]
        artifacts = Path('data/evaluation-artifacts') / evaluation_run_id
        audit_path = artifacts / 'retrieval-audit-sample.jsonl'
        selected = set()
        if audit_path.exists():
            selected = {json.loads(line)['retrieval_observation_id'] for line in audit_path.read_text(
                encoding='utf-8').splitlines() if line.strip()}
        audited = {str(observation_id) for sample, observation, judgment in values
                   if judgment and judgment.audit_status != 'pending'}
        quality_ready = bool(rows) and all(row['label'] for row in rows) and selected.issubset(audited)
        report = {'evaluation_run_id': evaluation_run_id, 'knowledge_freeze_sha256': run.knowledge_freeze_sha256,
                  'embedding_identity': run.embedding_identity, 'judge_identity': {'model': run.judge_model,
                  'prompt_version': run.judge_prompt_version, 'judge_run_id': run.judge_run_id},
                  'sample_count': len({row['sample_id'] for row in rows}), 'quality_ready': quality_ready,
                  'sources': {source: channel_summary([row for row in rows if source == 'overall' or row['sample_source'] == source])
                              for source in ('overall', 'real', 'synthetic_v2')}}
        if not quality_ready:
            report['quality_status'] = 'not_available_incomplete_judgments_or_audits'
        return report
    finally:
        await database.close()


def render_markdown(report):
    """渲染只有身份、计数、状态和耗时的 Markdown，不输出受控原文。"""
    lines = [f"# 检索评估报告：{report['evaluation_run_id']}", '',
             f"- 资料冻结 SHA-256：`{report['knowledge_freeze_sha256']}`",
             f"- 冻结样本数：{report['sample_count']}",
             f"- 质量指标可用：{'是' if report['quality_ready'] else '否'}", '',
             '| 来源 | 通道 | 观察数 | 成功 | 空结果 | 失败 | P50 ms | P95 ms | 最大 ms |',
             '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for source, channels in report['sources'].items():
        for channel, value in channels.items():
            lines.append('| {source} | {channel} | {observation_count} | {succeeded_count} | {empty_count} | '
                         '{failed_count} | {p50_ms} | {p95_ms} | {max_ms} |'.format(source=source,
                         channel=channel, **value))
    if not report['quality_ready']:
        lines.extend(('', '质量指标未输出：Codex 初标或规定人工抽检尚未完整导入。'))
    return '\n'.join(lines) + '\n'


def run_async(coroutine):
    """在 Windows 为 Psycopg 选择兼容事件循环。"""
    if sys.platform != 'win32':
        return asyncio.run(coroutine)
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


def main():
    """按所选格式输出脱敏评估报告。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation-run-id', required=True)
    parser.add_argument('--format', choices=('json', 'markdown'), default='json')
    args = parser.parse_args()
    report = run_async(build_report(Settings(), args.evaluation_run_id))
    print(render_markdown(report) if args.format == 'markdown' else json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
