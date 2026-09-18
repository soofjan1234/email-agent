"""在独立数据库验证评估运行和冻结样本不会被同名运行改写。"""
import uuid

import pytest

from models import Email
from services.evaluation import EvaluationError, EvaluationService


async def seed_email(database):
    """创建只用于评估存储测试的隔离业务邮件。"""
    async with database.session() as session:
        email = Email(client_request_id=f'{database.settings.mailbox_id}:evaluation:{uuid.uuid4()}',
            from_address='customer@example.invalid', subject='Support request', body_text='Need help',
            graph_thread_id=f'evaluation:{uuid.uuid4()}', workflow_generation=1)
        session.add(email)
        await session.flush()
        return email.id


async def test_same_run_id_cannot_change_identity_or_frozen_samples(database):
    """运行身份和样本成员一旦写入，后续调用只能读取同一事实。"""
    service = EvaluationService(database)
    run_id = 'evaluation-contract-' + uuid.uuid4().hex
    run = await service.create_run(evaluation_run_id=run_id, purpose='retrieval',
        knowledge_freeze_sha256='a' * 64, embedding_identity={'model': 'test'}, random_seed=7, code_version='test')
    repeated = await service.create_run(evaluation_run_id=run_id, purpose='retrieval',
        knowledge_freeze_sha256='a' * 64, embedding_identity={'model': 'test'}, random_seed=7, code_version='test')
    assert repeated.id == run.id
    with pytest.raises(EvaluationError, match='evaluation_run_immutable'):
        await service.create_run(evaluation_run_id=run_id, purpose='retrieval',
            knowledge_freeze_sha256='b' * 64, embedding_identity={'model': 'test'}, random_seed=7, code_version='test')
    email_id = await seed_email(database)
    await service.freeze_samples(run_id, [{'email_id': email_id, 'sample_source': 'real',
        'included': True, 'exclusion_reason': None}])
    with pytest.raises(EvaluationError, match='evaluation_samples_immutable'):
        await service.freeze_samples(run_id, [])
