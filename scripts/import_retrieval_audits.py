"""导入人工抽检结果；更正保留为追加字段，不覆盖 Codex 初标。"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import uuid

from config import Settings
from db import Database
from services.evaluation import EvaluationService


def read_audits(path):
    """读取严格 JSONL 抽检事实，并将观察 ID 解析为 UUID。"""
    audits = []
    for number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            audits.append({'retrieval_observation_id': uuid.UUID(row['retrieval_observation_id']),
                           'audit_status': row.get('audit_status'), 'final_label': row.get('final_label')})
        except (json.JSONDecodeError, KeyError, ValueError) as error:
            raise ValueError(f'invalid_audit_line_{number}') from error
    return audits


async def import_file(settings, evaluation_run_id, path):
    """以服务层校验一次性写入人工抽检结论。"""
    database = Database(settings)
    try:
        await database.check_ready()
        audits = read_audits(path)
        await EvaluationService(database).apply_audits(evaluation_run_id, audits)
        return {'evaluation_run_id': evaluation_run_id, 'audit_count': len(audits)}
    finally:
        await database.close()


def run_async(coroutine):
    """在 Windows 为 Psycopg 选择兼容事件循环。"""
    if sys.platform != 'win32':
        return asyncio.run(coroutine)
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


def main():
    """解析人工抽检文件路径。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation-run-id', required=True)
    parser.add_argument('--input', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run_async(import_file(Settings(), args.evaluation_run_id, args.input)), ensure_ascii=False,
                     sort_keys=True))


if __name__ == '__main__':
    main()
