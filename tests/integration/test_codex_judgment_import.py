"""验证 Codex 初标导入必须完整覆盖冻结候选且不允许回填 judge 身份。"""
import uuid

import pytest

from models import Email
from services.evaluation import EvaluationError, EvaluationService


async def test_judgment_import_rejects_unfrozen_judge_identity(database):
    """运行未在创建时固定 judge 身份时，导入不能修改已冻结运行。"""
    service = EvaluationService(database)
    run_id = 'judge-import-' + uuid.uuid4().hex
    await service.create_run(evaluation_run_id=run_id, purpose='retrieval', knowledge_freeze_sha256='a' * 64,
        embedding_identity={'model': 'test'}, random_seed=1, code_version='test')
    async with database.session() as session:
        email = Email(client_request_id=f'{database.settings.mailbox_id}:judge:{uuid.uuid4()}',
            from_address='customer@example.invalid', subject='Question', body_text='Help',
            graph_thread_id=f'judge:{uuid.uuid4()}', workflow_generation=1)
        session.add(email)
        await session.flush()
        email_id = email.id
    await service.freeze_samples(run_id, [{'email_id': email_id, 'sample_source': 'real',
                                           'included': True, 'exclusion_reason': None}])
    sample, _ = (await service.frozen_samples(run_id))[0]
    await service.record_observations(run_id, sample.id, 'keyword', [{'raw_rank': 1, 'candidate_chunk_id': None,
        'candidate_version': None, 'duration_ms': 1, 'status': 'empty', 'failure_code': None}])
    with pytest.raises(EvaluationError, match='judge_identity_not_frozen'):
        await service.import_judgments(run_id, judge_model='codex', prompt_version='judge-v1', judge_run_id='run-1',
            judgments=[])
