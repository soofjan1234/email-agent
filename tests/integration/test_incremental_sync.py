"""B1 用真实 PostgreSQL 验证 IMAP UID 游标与新邮件幂等入库。"""
import uuid

from email.message import EmailMessage

from sqlalchemy import select

from models import Email, MailboxSyncState, MailSyncJob
from services.mail_sync import IncomingMail, IncrementalBatch, MailSyncService


def raw_mail(uid):
    """生成拥有稳定 Message-ID 的模拟新收件。"""
    message = EmailMessage()
    message['Message-ID'] = f'<{uid}@example.test>'
    message['From'] = 'customer@example.test'
    message['To'] = 'support@example.test'
    message['Subject'] = f'Question {uid}'
    message.set_content(f'Please help with ticket {uid}.')
    return message.as_bytes()


class FakeIncrementalAdapter:
    """只提供 B1 所需的已排序 IMAP 增量批次，不产生网络访问。"""

    def __init__(self, uidvalidity, mails):
        self.uidvalidity = uidvalidity
        self.mails = mails
        self.requested_cursors = []

    def fetch_inbox_after(self, cursor):
        self.requested_cursors.append(cursor)
        return IncrementalBatch(self.uidvalidity, tuple(mail for mail in self.mails if mail.uid > cursor))


async def completed_history(database, uidvalidity='77', last_uid=100):
    """建立已完成 A 阶段及其不可变 IMAP 边界。"""
    async with database.session() as session:
        job = MailSyncJob(id=uuid.uuid4(), mailbox_id=database.settings.mailbox_id,
                          mode='historical_backfill', status='succeeded', stage='completed',
                          initialization_boundary={'imap': {'uidvalidity': uidvalidity, 'last_uid': last_uid}})
        session.add(job)
    return job.id


async def pending_incremental(database):
    """登记一次等待 worker 消费的用户增量请求。"""
    async with database.session() as session:
        job = MailSyncJob(id=uuid.uuid4(), mailbox_id=database.settings.mailbox_id,
                          mode='incremental', sync_request_id=str(uuid.uuid4()), status='pending')
        session.add(job)
    return job.id


async def test_incremental_uid_cursor_commits_with_new_emails(database):
    """从 A 的 UID 边界开始读取，并在重放时保持一封业务邮件唯一。"""
    await completed_history(database)
    job_id = await pending_incremental(database)
    mails = tuple(IncomingMail(uid, raw_mail(uid)) for uid in (101, 102))
    adapter = FakeIncrementalAdapter('77', mails)
    service = MailSyncService(database, adapter=adapter, page_size=1)

    assert await service.run_incremental(job_id)

    async with database.session() as session:
        state = await session.get(MailboxSyncState, database.settings.mailbox_id)
        job = await session.get(MailSyncJob, job_id)
        emails = list((await session.scalars(select(Email).where(
            Email.client_request_id.startswith(database.settings.mailbox_id + ':imap:')).order_by(Email.subject))).all())
        assert state.uidvalidity == '77' and state.last_committed_uid == 102
        assert job.status == 'succeeded' and job.cursor_before == {'uidvalidity': '77', 'uid': 100}
        assert job.cursor_after == {'uidvalidity': '77', 'uid': 102}
        assert [email.subject for email in emails] == ['Question 101', 'Question 102']
    assert adapter.requested_cursors == [100]


async def test_uidvalidity_change_fails_without_advancing_cursor(database):
    """文件夹 UID 版本变化必须进入可查询失败，不能继续使用旧游标。"""
    await completed_history(database, uidvalidity='77', last_uid=100)
    first_job = await pending_incremental(database)
    first = MailSyncService(database, adapter=FakeIncrementalAdapter('77', ()))
    assert await first.run_incremental(first_job)
    second_job = await pending_incremental(database)
    second = MailSyncService(database, adapter=FakeIncrementalAdapter('88', (IncomingMail(101, raw_mail(101)),)))

    assert not await second.run_incremental(second_job)

    async with database.session() as session:
        state = await session.get(MailboxSyncState, database.settings.mailbox_id)
        job = await session.get(MailSyncJob, second_job)
        assert state.uidvalidity == '77' and state.last_committed_uid == 100
        assert job.status == 'failed' and job.failure_type == 'cursor_reset_required'
