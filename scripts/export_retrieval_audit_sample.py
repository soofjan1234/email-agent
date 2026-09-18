"""导出分层人工抽检集合；低置信度和 no_answer 全量纳入，其余每层取 10%。"""
import argparse
import asyncio
import json
from math import ceil
from pathlib import Path
import random
import sys

from sqlalchemy import select

from config import Settings
from db import Database
from models import EvaluationRun, EvaluationSample, RetrievalJudgment, RetrievalObservation


def select_audits(rows, seed):
    """在固定随机种子下按来源、通道和初标标签分层选择人工抽检 ID。"""
    selected, grouped = {}, {}
    for row in rows:
        if row['confidence'] <= 2 or row['codex_label'] == 'no_answer':
            selected[row['retrieval_observation_id']] = row
        else:
            grouped.setdefault((row['sample_source'], row['channel'], row['codex_label']), []).append(row)
    randomizer = random.Random(seed)
    for group in grouped.values():
        randomizer.shuffle(group)
        for row in group[:ceil(len(group) * 0.1)]:
            selected[row['retrieval_observation_id']] = row
    return [selected[key] for key in sorted(selected)]


async def export(settings, evaluation_run_id):
    """从已导入初标导出不可覆盖的脱敏人工抽检 JSONL。"""
    target = Path('data/evaluation-artifacts') / evaluation_run_id / 'retrieval-audit-sample.jsonl'
    if target.exists():
        raise FileExistsError('audit_sample_already_exists')
    database = Database(settings)
    try:
        await database.check_ready()
        async with database.session() as session:
            run = await session.scalar(select(EvaluationRun).where(EvaluationRun.evaluation_run_id == evaluation_run_id))
            if run is None:
                raise ValueError('unknown_evaluation_run')
            values = (await session.execute(select(RetrievalJudgment, RetrievalObservation, EvaluationSample).
                select_from(RetrievalJudgment).join(RetrievalObservation,
                RetrievalJudgment.retrieval_observation_id == RetrievalObservation.id).join(EvaluationSample,
                RetrievalObservation.evaluation_sample_id == EvaluationSample.id).where(
                EvaluationSample.evaluation_run_id == run.id))).all()
        rows = [{'retrieval_observation_id': str(observation.id), 'sample_source': sample.sample_source,
                 'channel': observation.channel, 'codex_label': judgment.codex_label,
                 'confidence': judgment.confidence} for judgment, observation, sample in values]
        if not rows:
            raise ValueError('judgments_not_imported')
        selected = select_audits(rows, run.random_seed)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('\n'.join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in selected) + '\n',
                          encoding='utf-8')
        return {'evaluation_run_id': evaluation_run_id, 'audit_sample_count': len(selected)}
    finally:
        await database.close()


def run_async(coroutine):
    """在 Windows 为 Psycopg 选择兼容事件循环。"""
    if sys.platform != 'win32':
        return asyncio.run(coroutine)
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


def main():
    """导出显式检索运行的固定抽检集合。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation-run-id', required=True)
    args = parser.parse_args()
    print(json.dumps(run_async(export(Settings(), args.evaluation_run_id)), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
