"""导入覆盖全部盲化候选的 Codex 初标，拒绝映射、标签或身份不一致。"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import uuid

from config import Settings
from db import Database
from services.evaluation import EvaluationError, EvaluationService


def read_jsonl(path):
    """读取非空 JSONL 行；每行必须是对象，禁止静默跳过坏数据。"""
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f'invalid_jsonl_line_{number}') from error
        if not isinstance(item, dict):
            raise ValueError(f'invalid_jsonl_line_{number}')
        rows.append(item)
    return rows


def prepare_judgments(mapping_path, rows):
    """将盲化 ID 恢复为观察记录 ID，并验证每行使用同一映射哈希。"""
    payload = json.loads(Path(mapping_path).read_text(encoding='utf-8'))
    mapping, digest = payload.get('mapping'), payload.get('mapping_sha256')
    actual = hashlib.sha256(json.dumps(mapping, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    if not isinstance(mapping, dict) or digest != actual:
        raise ValueError('mapping_hash_mismatch')
    prepared = []
    for row in rows:
        blind_id, candidate_id = row.get('blind_id'), row.get('candidate_id')
        entry = mapping.get(blind_id)
        if row.get('mapping_sha256') != digest or not entry or candidate_id not in entry.get('observation_ids', []):
            raise ValueError('judgment_mapping_mismatch')
        prepared.append({'retrieval_observation_id': uuid.UUID(candidate_id),
                         'blinded_rank': entry['observation_ids'].index(candidate_id) + 1,
                         'label': row.get('label'), 'confidence': row.get('confidence'),
                         'rationale': row.get('rationale')})
    return prepared


async def import_file(settings, evaluation_run_id, path, judge_model, prompt_version, judge_run_id):
    """校验文件后以单一事务写入，任何一行异常均不保留部分初标。"""
    artifact = Path('data/evaluation-artifacts') / evaluation_run_id
    judgments = prepare_judgments(artifact / 'codex-judge-mapping.json', read_jsonl(path))
    database = Database(settings)
    try:
        await database.check_ready()
        await EvaluationService(database).import_judgments(evaluation_run_id, judge_model=judge_model,
            prompt_version=prompt_version, judge_run_id=judge_run_id, judgments=judgments)
        return {'evaluation_run_id': evaluation_run_id, 'judgment_count': len(judgments)}
    finally:
        await database.close()


def run_async(coroutine):
    """在 Windows 为 Psycopg 选择兼容事件循环。"""
    if sys.platform != 'win32':
        return asyncio.run(coroutine)
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


def main():
    """解析显式 judge 身份和输入路径。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation-run-id', required=True)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--judge-model', required=True)
    parser.add_argument('--prompt-version', required=True)
    parser.add_argument('--judge-run-id', required=True)
    args = parser.parse_args()
    print(json.dumps(run_async(import_file(Settings(), args.evaluation_run_id, args.input, args.judge_model,
                                            args.prompt_version, args.judge_run_id)), ensure_ascii=False,
                     sort_keys=True))


if __name__ == '__main__':
    main()
