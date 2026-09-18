"""导出盲化的本地检索判定输入；不包含通道名、地址、凭据或数据库位置。"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import random
import re
import sys

from sqlalchemy import select

from config import Settings
from db import Database
from models import Email, EvaluationRun, EvaluationSample, KnowledgeChunk, RetrievalObservation


ADDRESS = re.compile(r'[\w.+-]+@[\w.-]+')


def safe_text(text):
    """仅用于受控人工判定输入，屏蔽邮件地址并限制单条长度。"""
    return ADDRESS.sub('[redacted-address]', (text or '').strip())[:4000]


async def export(settings, evaluation_run_id):
    """按样本和通道稳定随机化候选，并写入不可覆盖的 JSONL 与映射哈希。"""
    target = Path('data/evaluation-artifacts') / evaluation_run_id
    inputs_path, mapping_path = target / 'codex-judge-inputs.jsonl', target / 'codex-judge-mapping.json'
    if inputs_path.exists() or mapping_path.exists():
        raise FileExistsError('judge_input_already_exists')
    database = Database(settings)
    try:
        await database.check_ready()
        async with database.session() as session:
            run = await session.scalar(select(EvaluationRun).where(EvaluationRun.evaluation_run_id == evaluation_run_id))
            if run is None or run.purpose != 'retrieval':
                raise ValueError('unknown_retrieval_evaluation_run')
            rows = (await session.execute(select(EvaluationSample, Email, RetrievalObservation, KnowledgeChunk).join(
                Email, EvaluationSample.email_id == Email.id).join(RetrievalObservation,
                RetrievalObservation.evaluation_sample_id == EvaluationSample.id).outerjoin(KnowledgeChunk,
                RetrievalObservation.candidate_chunk_id == KnowledgeChunk.id).where(
                EvaluationSample.evaluation_run_id == run.id, EvaluationSample.included).order_by(
                EvaluationSample.id, RetrievalObservation.channel, RetrievalObservation.raw_rank))).all()
        grouped = {}
        for sample, email, observation, chunk in rows:
            grouped.setdefault((str(sample.id), observation.channel), {'email': email, 'rows': []})['rows'].append(
                (observation, chunk))
        randomizer, mapping, lines = random.Random(run.random_seed), {}, []
        for (sample_id, channel), group in sorted(grouped.items()):
            candidates = [{'candidate_id': str(observation.id), 'content_hash': hashlib.sha256(
                (chunk.content if chunk else '').encode('utf-8')).hexdigest(), 'content': safe_text(chunk.content) if chunk else '',
                'empty': observation.status == 'empty'} for observation, chunk in group['rows']]
            randomizer.shuffle(candidates)
            blind_id = hashlib.sha256(f'{evaluation_run_id}:{sample_id}:{channel}'.encode()).hexdigest()[:20]
            mapping[blind_id] = {'sample_id': sample_id, 'channel': channel,
                                 'observation_ids': [item['candidate_id'] for item in candidates]}
            lines.append({'blind_id': blind_id, 'sample_source': 'real' if group['email'].client_request_id.startswith(
                'imap-shadow-20260918:history:') else 'synthetic_v2',
                'mail_problem': safe_text(group['email'].subject + '\n' + group['email'].body_text),
                'candidates': candidates})
        target.mkdir(parents=True, exist_ok=True)
        inputs_path.write_text('\n'.join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in lines) + '\n',
                               encoding='utf-8')
        mapping_text = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        mapping_path.write_text(json.dumps({'mapping_sha256': hashlib.sha256(mapping_text.encode()).hexdigest(),
                                            'mapping': mapping}, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                                encoding='utf-8')
        return {'input_count': len(lines), 'mapping_sha256': hashlib.sha256(mapping_text.encode()).hexdigest()}
    finally:
        await database.close()


def run_async(coroutine):
    """在 Windows 为 Psycopg 选择兼容事件循环。"""
    if sys.platform != 'win32':
        return asyncio.run(coroutine)
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


def main():
    """导出显式运行的判定输入。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation-run-id', required=True)
    args = parser.parse_args()
    print(json.dumps(run_async(export(Settings(), args.evaluation_run_id)), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
