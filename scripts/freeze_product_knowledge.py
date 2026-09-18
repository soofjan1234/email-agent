"""冻结评估使用的官方产品知识快照，禁止后续运行依赖可变的当前知识库。"""
import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path

from sqlalchemy import func, select

from config import Settings
from db import Database
from models import KnowledgeChunk, KnowledgeDocument


REQUIRED_METADATA = ('official_url', 'retrieved_at', 'applicable_models', 'applicable_scope')
FREEZE_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')


def validate_freeze_id(freeze_id):
    """仅接受可安全映射为受控目录名的冻结标识。"""
    if not isinstance(freeze_id, str) or not FREEZE_ID.fullmatch(freeze_id):
        raise ValueError('invalid_freeze_id')


def artifact_path(freeze_id, root=Path('data/evaluation-artifacts')):
    """返回冻结清单的唯一目标文件，不创建或覆盖已有目录。"""
    validate_freeze_id(freeze_id)
    return root / freeze_id / 'knowledge-freeze.json'


def validate_documents(documents):
    """在写入前校验数量、内容唯一性和评估所需的官方来源字段。"""
    if not 8 <= len(documents) <= 12:
        raise ValueError('product_document_count_out_of_range')
    hashes = [document.content_hash for document in documents]
    if any(not item for item in hashes) or len(set(hashes)) != len(hashes):
        raise ValueError('duplicate_or_missing_content_hash')
    for document in documents:
        metadata = document.source_metadata or {}
        if any(not metadata.get(field) for field in REQUIRED_METADATA):
            raise ValueError('missing_official_source_metadata')


async def build_freeze(settings, freeze_id, root=Path('data/evaluation-artifacts')):
    """从 active product_doc 生成不可变清单，并记录分块和编码身份。"""
    target = artifact_path(freeze_id, root)
    if target.parent.exists():
        raise FileExistsError('freeze_id_already_exists')
    database = Database(settings)
    try:
        await database.check_ready()
        async with database.session() as session:
            documents = list((await session.scalars(select(KnowledgeDocument).where(
                KnowledgeDocument.source_type == 'product_doc', KnowledgeDocument.status == 'active').order_by(
                KnowledgeDocument.source_ref, KnowledgeDocument.version))).all())
            validate_documents(documents)
            chunk_counts = dict((await session.execute(select(KnowledgeChunk.document_id, func.count()).where(
                KnowledgeChunk.document_id.in_([document.id for document in documents])).group_by(
                KnowledgeChunk.document_id))).all())
        payload = {
            'freeze_id': freeze_id,
            'documents': [{'id': str(document.id), 'version': document.version,
                           'content_hash': document.content_hash, 'chunk_count': chunk_counts.get(document.id, 0),
                           'document_sha256': hashlib.sha256((document.raw_content or '').encode('utf-8')).hexdigest()}
                          for document in documents],
            'document_count': len(documents),
            'chunk_count': sum(chunk_counts.values()),
            'chunker_version': 'markdown-v1',
            'embedding_identity': settings.embedding_identity(),
            'index_version': settings.embedding_index_version,
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        payload['freeze_sha256'] = hashlib.sha256(serialized).hexdigest()
        target.parent.mkdir(parents=True, exist_ok=False)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        return {'freeze_id': freeze_id, 'freeze_sha256': payload['freeze_sha256'],
                'document_count': payload['document_count'], 'chunk_count': payload['chunk_count']}
    finally:
        await database.close()


def run_async(coroutine):
    """在 Windows 上选择 Psycopg 可用的 Selector 事件循环。"""
    if sys.platform != 'win32':
        return asyncio.run(coroutine)
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


def main():
    """解析冻结 ID 并只输出可公开的审计汇总。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze-id', required=True)
    args = parser.parse_args()
    print(json.dumps(run_async(build_freeze(Settings(), args.freeze_id)), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
