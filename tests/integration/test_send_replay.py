"""B3 验证审核落库后恢复失败可由同一请求补齐。"""
import uuid

import pytest
from sqlalchemy import func, select

from models import Email, Review, SimulatedOutbox
from services.dispatch import WorkflowDispatcher
from services.reviews import ReviewError, ReviewService


class FixedProcessor:
    """固定生成等待审核草稿。"""

    async def process(self, state):
        return {'phase': 'awaiting_review', 'category': 'network', 'priority': 'normal', 'risk': 'none',
                'decision': {'category': 'network', 'priority': 'normal', 'risks': [],
                             'knowledge_status': 'sufficient', 'reason': 'fixture',
                             'missing_information': [], 'citations': [],
                             'reply_draft': 'Safe draft.', 'requires_human_review': True},
                'retrieval_attempts': 1, 'generation_attempts': 1, 'validation_errors': []}


class FailResumeOnce:
    """在审核事实提交后模拟进程未能恢复 Graph。"""

    def __init__(self, delegate):
        self.delegate = delegate
        self.failed = False

    async def get_state(self, email_id):
        return await self.delegate.get_state(email_id)

    async def resume_review(self, email_id, checkpoint_id, review):
        if not self.failed:
            self.failed = True
            raise RuntimeError('injected_resume_failure')
        return await self.delegate.resume_review(email_id, checkpoint_id, review)


async def test_review_saved_before_resume_is_completed_by_replay(database):
    """首次恢复失败保留审核事实，重试补齐且模拟发件仍唯一。"""
    email_id = uuid.uuid4()
    thread_id = f'email:{email_id}:generation:1'
    async with database.session() as session:
        session.add(Email(id=email_id, client_request_id=f'{database.settings.mailbox_id}:replay:{email_id}',
            from_address='customer@example.test', subject='NAS', body_text='Help',
            graph_thread_id=thread_id, workflow_generation=1))
    dispatcher = WorkflowDispatcher(database, FixedProcessor())
    snapshot = await dispatcher.dispatch_email(email_id)
    payload = {'review_request_id': str(uuid.uuid4()), 'graph_thread_id': thread_id,
               'checkpoint_id': snapshot.config['configurable']['checkpoint_id'], 'action': 'approve',
               'final_content': None, 'reviewer': 'operator', 'comment': None}

    with pytest.raises(ReviewError, match='resume_conflict'):
        await ReviewService(database, FailResumeOnce(dispatcher)).submit(email_id, payload)
    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Review).where(
            Review.email_id == email_id)) == 1
        assert await session.scalar(select(func.count()).select_from(SimulatedOutbox).where(
            SimulatedOutbox.email_id == email_id)) == 0

    completed = await ReviewService(database, dispatcher).submit(email_id, payload)
    assert completed['completed']
    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(SimulatedOutbox).where(
            SimulatedOutbox.email_id == email_id)) == 1
