"""B1/B2 使用真实 PostgreSQL checkpoint 验证同一 thread 恢复。"""
import uuid

from sqlalchemy import select

from models import Email
from services.dispatch import WorkflowDispatcher


class FixedProcessor:
    """不访问模型或检索，固定生成一份可审核状态。"""

    async def process(self, state):
        return {'phase': 'awaiting_review', 'category': 'network', 'priority': 'normal', 'risk': 'none',
                'decision': {'category': 'network', 'priority': 'normal', 'risks': [],
                             'knowledge_status': 'sufficient', 'reason': 'fixture',
                             'missing_information': [], 'citations': [],
                             'reply_draft': 'Draft for review.', 'requires_human_review': True},
                'retrieval_attempts': 1, 'generation_attempts': 1, 'validation_errors': []}


async def seed_email(database):
    """创建带确定 thread 的当前邮箱业务邮件。"""
    email_id = uuid.uuid4()
    async with database.session() as session:
        session.add(Email(id=email_id, client_request_id=f'{database.settings.mailbox_id}:graph:{email_id}',
                          from_address='customer@example.test', subject='NAS help', body_text='Cannot connect',
                          graph_thread_id=f'email:{email_id}:generation:1', workflow_generation=1))
    return email_id


async def test_new_dispatcher_recovers_same_interrupt_and_repairs_projection(database):
    """新调度实例从数据库恢复同一 checkpoint，不重新生成业务路径。"""
    email_id = await seed_email(database)
    first = await WorkflowDispatcher(database, FixedProcessor()).dispatch_email(email_id)
    checkpoint_id = first.config['configurable']['checkpoint_id']
    assert first.values['phase'] == 'awaiting_review' and first.next

    async with database.session() as session:
        email = await session.get(Email, email_id)
        email.status = 'received'

    recovered = await WorkflowDispatcher(database, FixedProcessor()).dispatch_email(email_id)
    assert recovered.config['configurable']['checkpoint_id'] == checkpoint_id
    async with database.session() as session:
        assert (await session.get(Email, email_id)).status == 'awaiting_review'


async def test_same_thread_concurrent_dispatch_has_one_persisted_path(database):
    """同一 thread 并发启动最终只保留一条可恢复路径。"""
    import asyncio
    email_id = await seed_email(database)
    dispatcher = WorkflowDispatcher(database, FixedProcessor())
    await asyncio.gather(dispatcher.dispatch_email(email_id), dispatcher.dispatch_email(email_id))
    snapshot = await dispatcher.get_state(email_id)
    assert snapshot.values['email_id'] == str(email_id)
    assert snapshot.values['generation_attempts'] == 1
    async with database.session() as session:
        rows = list((await session.scalars(select(Email).where(Email.id == email_id))).all())
        assert len(rows) == 1
