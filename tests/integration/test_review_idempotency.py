"""B3 使用真实数据库与 checkpoint 验证审核重放和冲突。"""
import uuid

import pytest
from sqlalchemy import func, select

from models import CaseCandidate, Email, Review, SimulatedOutbox
from services.dispatch import WorkflowDispatcher
from services.reviews import ReviewError, ReviewService


class FixedProcessor:
    """固定生成一份等待审核的有依据草稿。"""

    async def process(self, state):
        return {'phase': 'awaiting_review', 'category': 'network', 'priority': 'normal', 'risk': 'none',
                'decision': {'category': 'network', 'priority': 'normal', 'risks': [],
                             'knowledge_status': 'sufficient', 'reason': 'fixture',
                             'missing_information': [], 'citations': [],
                             'reply_draft': 'Use the documented setting.', 'requires_human_review': True},
                'retrieval_attempts': 1, 'generation_attempts': 1, 'validation_errors': []}


async def waiting_email(database):
    """创建并运行到真实 interrupt，返回审核所需身份。"""
    email_id = uuid.uuid4()
    thread_id = f'email:{email_id}:generation:1'
    async with database.session() as session:
        session.add(Email(id=email_id, client_request_id=f'{database.settings.mailbox_id}:review:{email_id}',
            from_address='customer@example.test', subject='NAS help', body_text='Cannot connect',
            graph_thread_id=thread_id, workflow_generation=1))
    dispatcher = WorkflowDispatcher(database, FixedProcessor())
    snapshot = await dispatcher.dispatch_email(email_id)
    return email_id, thread_id, snapshot.config['configurable']['checkpoint_id'], dispatcher


def review_payload(thread_id, checkpoint_id, action='approve', request_id=None):
    """生成一项稳定审核请求。"""
    return {'review_request_id': request_id or str(uuid.uuid4()), 'graph_thread_id': thread_id,
            'checkpoint_id': checkpoint_id, 'action': action, 'final_content': None,
            'reviewer': 'operator', 'comment': None}


async def test_approved_review_replay_creates_one_outbox_and_candidate(database):
    """批准重放只产生一个审核事实、一条模拟发件和一个非 active 候选。"""
    email_id, thread_id, checkpoint_id, dispatcher = await waiting_email(database)
    payload = review_payload(thread_id, checkpoint_id)
    service = ReviewService(database, dispatcher)
    first = await service.submit(email_id, payload)
    second = await service.submit(email_id, payload)
    assert first['id'] == second['id'] and second['completed']

    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(Review).where(
            Review.email_id == email_id)) == 1
        assert await session.scalar(select(func.count()).select_from(SimulatedOutbox).where(
            SimulatedOutbox.email_id == email_id)) == 1
        candidates = list((await session.scalars(select(CaseCandidate).where(
            CaseCandidate.email_id == email_id))).all())
        assert len(candidates) == 1 and candidates[0].status == 'candidate'


@pytest.mark.parametrize('action', ['reject', 'manual_review'])
async def test_non_approved_review_never_writes_outbox(database, action):
    """拒绝和转人工都只能记录决定，不能模拟发件。"""
    email_id, thread_id, checkpoint_id, dispatcher = await waiting_email(database)
    await ReviewService(database, dispatcher).submit(email_id,
        review_payload(thread_id, checkpoint_id, action))
    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(SimulatedOutbox).where(
            SimulatedOutbox.email_id == email_id)) == 0
        expected = 'rejected' if action == 'reject' else 'manual_review'
        assert (await session.get(Email, email_id)).status == expected


async def test_stale_checkpoint_is_rejected_without_review(database):
    """旧页面携带的 checkpoint 不能覆盖当前人工等待。"""
    email_id, thread_id, _, dispatcher = await waiting_email(database)
    with pytest.raises(ReviewError) as caught:
        await ReviewService(database, dispatcher).submit(email_id,
            review_payload(thread_id, 'stale-checkpoint'))
    assert caught.value.code == 'stale_checkpoint'
