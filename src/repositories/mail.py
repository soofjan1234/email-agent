"""同步任务与历史原文的数据访问；事务边界由 MailSyncService 组织。"""
from contextlib import asynccontextmanager
import asyncio
import hashlib
import uuid

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.mailbox import parse_message
from models import MailMessage, MailSyncJob


def mailbox_lock_key(mailbox_id):
    """使用稳定带命名空间的 64 位键，在多个进程中锁定同一邮箱。"""
    digest = hashlib.blake2b(('email-agent:mailbox:' + mailbox_id).encode(), digest_size=8).digest()
    return int.from_bytes(digest, 'big', signed=True)


@asynccontextmanager
async def locked_mailbox(database, mailbox_id):
    """锁与全部业务事务共用同一连接；进程退出或断线自动释放会话锁。"""
    key = mailbox_lock_key(mailbox_id)
    async with database.engine.connect() as connection:
        acquired = await connection.scalar(text('SELECT pg_try_advisory_lock(:key)'), {'key': key})
        await connection.commit()
        if not acquired:
            yield None
            return
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                yield session
        finally:
            # 先回滚未完成事务，再释放锁；释放异常时丢弃连接，不能带锁归还池。
            try:
                if not connection.invalidated and not connection.closed:
                    if connection.in_transaction():
                        await connection.rollback()
                    await connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': key})
                    await connection.commit()
            except Exception:
                await connection.invalidate()


class MailRepository:
    """仅封装明确的同步查询和批次写入，不自行提交事务。"""

    @staticmethod
    async def ensure_history(session, mailbox_id):
        """唯一部分索引保证多个启动入口只创建一项历史任务。"""
        await session.execute(insert(MailSyncJob).values(
            id=uuid.uuid4(), mailbox_id=mailbox_id, mode='historical_backfill'
        ).on_conflict_do_nothing(index_elements=['mailbox_id'],
                                index_where=MailSyncJob.mode == 'historical_backfill'))
        return await session.scalar(select(MailSyncJob.id).where(
            MailSyncJob.mailbox_id == mailbox_id, MailSyncJob.mode == 'historical_backfill'))

    @staticmethod
    async def save_page(session, job, sources):
        """保存邮件但不更新游标，使服务层能将两者放入同一事务。"""
        added, skipped, failed = 0, 0, 0
        for source in sources:
            parsed = await asyncio.to_thread(parse_message, source.raw_content)
            identity = '\0'.join((source.folder, parsed['message_id'] or '', source.content_hash))
            key = hashlib.sha256(identity.encode()).hexdigest()
            inserted = await session.scalar(insert(MailMessage).values(
                id=uuid.uuid4(), mailbox_id=job.mailbox_id, sync_job_id=job.id,
                source_id=source.id, dedup_key=key, folder=source.folder, **parsed
            ).on_conflict_do_nothing(constraint='message_mailbox_identity').returning(MailMessage.id))
            if inserted:
                added += 1
                failed += int(parsed['parse_error'] is not None)
            else:
                skipped += 1
        await session.flush()
        return added, skipped, failed
