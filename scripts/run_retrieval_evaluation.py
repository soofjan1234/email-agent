"""在固定冻结资料上记录三通道 Top-3；不调用生成、审核、SMTP 或 IMAP。"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from sqlalchemy import select

from config import Settings
from db import Database
from models import Email, EvaluationSample
from services.evaluation import EvaluationError, EvaluationService
from services.retrieval import RetrievalError, RetrievalService
from workflow.nodes import SPAM_MARKERS


REAL_PREFIX = 'imap-shadow-20260918:history:'
V2_PREFIX = 'imap-shadow-20260918-synthetic-v2:history:'


def load_freeze(freeze_id):
    """读取冻结文件并校验其自描述哈希，拒绝可变的当前知识库。"""
    path = Path('data/evaluation-artifacts') / freeze_id / 'knowledge-freeze.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    expected = data.pop('freeze_sha256', None)
    actual = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    if not expected or expected != actual:
        raise ValueError('knowledge_freeze_hash_mismatch')
    return expected


def code_version():
    """记录当前代码版本；无 Git 信息时使用受控 unknown 而非伪造提交。"""
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def observation_rows(candidates, duration_ms):
    """将通道候选压缩为仅含 ID、版本、名次和耗时的审计事实。"""
    if not candidates:
        return [{'raw_rank': 1, 'candidate_chunk_id': None, 'candidate_version': None,
                 'duration_ms': duration_ms, 'status': 'empty', 'failure_code': None}]
    return [{'raw_rank': item.rank, 'candidate_chunk_id': item.chunk_id, 'candidate_version': item.version,
             'duration_ms': duration_ms, 'status': 'succeeded', 'failure_code': None} for item in candidates]


async def source_samples(database):
    """固定读取 32 条真实未回复邮件和 508 条 v2 非垃圾邮件，不接受其他来源。"""
    async with database.session() as session:
        rows = list((await session.scalars(select(Email).where(
            Email.client_request_id.startswith(REAL_PREFIX) | Email.client_request_id.startswith(V2_PREFIX)).order_by(
            Email.client_request_id))).all())
    samples = []
    for email in rows:
        text = (email.subject + '\n' + email.body_text).lower()
        if email.client_request_id.startswith(REAL_PREFIX):
            samples.append({'email_id': email.id, 'sample_source': 'real', 'included': True, 'exclusion_reason': None})
        elif not any(marker in text for marker in SPAM_MARKERS):
            samples.append({'email_id': email.id, 'sample_source': 'synthetic_v2', 'included': True,
                            'exclusion_reason': None})
    if sum(item['sample_source'] == 'real' for item in samples) != 32 or len(samples) != 540:
        raise ValueError('evaluation_sample_set_invalid')
    return samples


async def run(settings, freeze_id, evaluation_run_id, judge_model=None, judge_prompt_version=None, judge_run_id=None):
    """创建不可变运行并为每个未记录通道写入成功、空或失败事实。"""
    freeze_sha = load_freeze(freeze_id)
    database = Database(settings)
    try:
        await database.check_ready()
        service = EvaluationService(database)
        await service.create_run(evaluation_run_id=evaluation_run_id, purpose='retrieval',
            knowledge_freeze_sha256=freeze_sha, embedding_identity=settings.embedding_identity(), random_seed=20260918,
            code_version=code_version(), judge_model=judge_model, judge_prompt_version=judge_prompt_version,
            judge_run_id=judge_run_id)
        try:
            await service.freeze_samples(evaluation_run_id, await source_samples(database))
        except EvaluationError as error:
            if error.code != 'evaluation_samples_immutable':
                raise
        completed, failures = 0, 0
        for sample, email in await service.pending_retrieval_samples(evaluation_run_id):
            try:
                result = await RetrievalService(database).retrieve_product_channels(email.subject + '\n' + email.body_text)
                for channel in ('keyword', 'vector', 'rrf'):
                    try:
                        await service.record_observations(evaluation_run_id, sample.id, channel,
                            observation_rows(result[channel], result['durations_ms'][channel]))
                    except EvaluationError as error:
                        if error.code != 'retrieval_observations_immutable':
                            raise
                completed += 1
            except RetrievalError as error:
                failures += 1
                for channel in ('keyword', 'vector', 'rrf'):
                    try:
                        await service.record_observations(evaluation_run_id, sample.id, channel, [{
                            'raw_rank': 1, 'candidate_chunk_id': None, 'candidate_version': None,
                            'duration_ms': 0, 'status': 'failed', 'failure_code': error.code}])
                    except EvaluationError as immutable:
                        if immutable.code != 'retrieval_observations_immutable':
                            raise
        return {'evaluation_run_id': evaluation_run_id, 'freeze_sha256': freeze_sha,
                'completed_samples': completed, 'failed_samples': failures, 'query_rewrite_count': 0}
    finally:
        await database.close()


def run_async(coroutine):
    """在 Windows 为 Psycopg 选择兼容事件循环。"""
    if sys.platform != 'win32':
        return asyncio.run(coroutine)
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


def main():
    """只接受冻结 ID 和显式运行 ID，固定 Top-K=3 且关闭改写。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-id', required=True)
    parser.add_argument('--evaluation-run-id', required=True)
    parser.add_argument('--judge-model')
    parser.add_argument('--judge-prompt-version')
    parser.add_argument('--judge-run-id')
    args = parser.parse_args()
    judge_values = (args.judge_model, args.judge_prompt_version, args.judge_run_id)
    if any(judge_values) and not all(judge_values):
        parser.error('judge identity must provide model, prompt version, and run ID together')
    print(json.dumps(run_async(run(Settings(), args.freeze_id, args.evaluation_run_id, *judge_values)), ensure_ascii=False,
                     sort_keys=True))


if __name__ == '__main__':
    main()
