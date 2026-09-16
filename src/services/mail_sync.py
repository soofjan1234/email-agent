"""可恢复的历史初始化；快照、扫描、完整关系识别和候选生成均在 Graph 外。"""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from adapters.mailbox import MockMailboxAdapter
from evals.harness.normalize import extract_protected
from evals.harness.redact import redact_case_text
from models import AuditEvent, CaseCandidate, HistoricalEmailPair, MailMessage, MailSource, MailSyncJob
from repositories.mail import MailRepository, locked_mailbox
from services.pairing import identify_pairs


class MailSyncService:
    """每页原文与扫描进度原子提交，任意阶段中断都可重放。"""

    def __init__(self, database, adapter=None, page_size=None):
        """共享配置决定邮箱标识；适配器可注入受控模拟邮箱。"""
        self.database = database
        self.mailbox_id = database.settings.mailbox_id
        self.adapter = adapter or MockMailboxAdapter(database.settings.mailbox_root)
        self.page_size = page_size or database.settings.mail_sync_page_size

    async def ensure_initialization(self):
        """API 和 worker 启动只登记任务，不在启动检查中扫描文件。"""
        async with self.database.session() as session:
            return await MailRepository.ensure_history(session, self.mailbox_id)

    async def run_history(self, max_pages=None):
        """取得邮箱锁后恢复未完成任务；已成功或其他 worker 持锁时跳过。"""
        job_id = await self.ensure_initialization()
        async with locked_mailbox(self.database, self.mailbox_id) as session:
            if session is None:
                return False
            try:
                async with session.begin():
                    await self.database._verify_identity(session)
                    job = await session.get(MailSyncJob, job_id)
                    if job.status == 'succeeded':
                        return False
                    job.status = 'running'
                    job.failure_type = None
                    job.retryable = False
                # 1. 完整保存快照后才发布边界；失败时不会保留半个快照。
                if job.stage == 'snapshot':
                    await self._snapshot(session, job_id)
                pages = 0
                # 2. 原文写入与游标推进共享一次事务，崩溃只会重放未提交页。
                while job.stage == 'scanning':
                    await self._scan_page(session, job_id)
                    pages += 1
                    if max_pages is not None and pages >= max_pages:
                        return False
                # 3. 只有全量扫描结束才建立关系，后续批次不能推翻已发布候选。
                if job.stage == 'pairing':
                    await self._pair(session, job_id)
                while job.stage == 'candidates':
                    await self._candidates(session, job_id)
                return True
            except Exception as exc:
                # 锁连接一旦失效，禁止旧执行者重连写状态；其他进程可能已接管。
                if session.bind.invalidated or session.bind.closed:
                    raise
                await session.rollback()
                async with session.begin():
                    job = await session.get(MailSyncJob, job_id)
                    # 提交成功后的异常不能撤销数据库中已经完成的业务事实。
                    if job.status != 'succeeded':
                        job.status = 'failed'
                        job.failure_type = 'source_unavailable' if isinstance(exc, (OSError, ValueError)) else 'processing_error'
                        job.retryable = True
                raise

    async def _snapshot(self, session, job_id):
        """快照保留原始字节和内容哈希，新增文件留给后续增量同步。"""
        captured_at = datetime.now(timezone.utc).isoformat()
        snapshot = await asyncio.to_thread(self.adapter.capture)
        digest = hashlib.sha256()
        async with session.begin():
            job = await session.get(MailSyncJob, job_id)
            for ordinal, mail in enumerate(snapshot):
                digest.update(f'{mail.source_ref}\0{mail.content_hash}\n'.encode())
                session.add(MailSource(sync_job_id=job_id, ordinal=ordinal, folder=mail.folder,
                                       source_ref=mail.source_ref, content_hash=mail.content_hash,
                                       raw_content=mail.raw_content))
            job.initialization_boundary = {'snapshot_id': str(job_id), 'captured_at': captured_at,
                                            'sha256': digest.hexdigest(), 'file_count': len(snapshot)}
            job.stage = 'scanning'
            session.add(AuditEvent(event_type='history_snapshot_created', actor_type='system',
                                   request_id=str(job_id), data={'file_count': len(snapshot)}))

    async def _scan_page(self, session, job_id):
        """扫描位置只针对不可变快照，不依赖会变动的目录顺序或 mtime。"""
        async with session.begin():
            job = await session.get(MailSyncJob, job_id)
            sources = list((await session.scalars(select(MailSource).where(
                MailSource.sync_job_id == job_id, MailSource.ordinal >= job.scanned_count
            ).order_by(MailSource.ordinal).limit(self.page_size))).all())
            if not sources and job.scanned_count < job.initialization_boundary['file_count']:
                raise RuntimeError('snapshot_records_missing')
            added, skipped, failed = await MailRepository.save_page(session, job, sources)
            cursor = dict(job.scan_cursor)
            for source in sources:
                cursor[source.folder] += 1
            job.scan_cursor = cursor
            job.scanned_count += len(sources)
            job.added_count += added
            job.skipped_count += skipped
            job.failed_count += failed
            if job.scanned_count == job.initialization_boundary['file_count']:
                job.stage = 'pairing'

    async def _pair(self, session, job_id):
        """记录完整关系和未支持原因；不创建 emails 行或任何 Graph 标识。"""
        async with session.begin():
            job = await session.get(MailSyncJob, job_id)
            messages = list((await session.scalars(select(MailMessage).where(
                MailMessage.sync_job_id == job_id))).all())
            result = await asyncio.to_thread(identify_pairs, messages)
            by_id = {mail.id: mail for mail in messages}
            for mail in messages:
                mail.unsupported_reason = result.reasons.get(mail.id)
            for inbound_id, outbound_id in result.pairs:
                inbound, outbound = by_id[inbound_id], by_id[outbound_id]
                inserted = await session.scalar(insert(HistoricalEmailPair).values(
                    id=uuid.uuid5(job_id, f'{inbound_id}:{outbound_id}'), mailbox_id=job.mailbox_id,
                    sync_job_id=job_id, inbound_message_id=inbound.message_id,
                    outbound_message_id=outbound.message_id,
                    inbound_ref=f'mail-message:{inbound.id}', outbound_ref=f'mail-message:{outbound.id}',
                    pairing_method='header', pairing_confidence=1.0, status='needs_review'
                ).on_conflict_do_nothing().returning(HistoricalEmailPair.id))
                if inserted is None:
                    existing = await session.scalar(select(HistoricalEmailPair).where(
                        HistoricalEmailPair.mailbox_id == job.mailbox_id,
                        HistoricalEmailPair.inbound_message_id == inbound.message_id))
                    if (existing is None or existing.sync_job_id != job_id
                            or existing.outbound_message_id != outbound.message_id):
                        raise RuntimeError('pair_source_conflict')
            job.paired_count = len(result.pairs)
            job.unsupported_reasons = dict(Counter(result.reasons.values()))
            job.stage = 'candidates'

    async def _candidates(self, session, job_id):
        """保留完整脱敏问题和回复，不推断适用条件、不发布、不向量化。"""
        async with session.begin():
            job = await session.get(MailSyncJob, job_id)
            pairs = list((await session.scalars(select(HistoricalEmailPair).where(
                HistoricalEmailPair.sync_job_id == job_id
            ).order_by(HistoricalEmailPair.id).offset(job.candidate_count).limit(self.page_size))).all())
            if not pairs and job.candidate_count < job.paired_count:
                raise RuntimeError('candidate_source_missing')
            for pair in pairs:
                inbound = await session.get(MailMessage, uuid.UUID(pair.inbound_ref.removeprefix('mail-message:')))
                outbound = await session.get(MailMessage, uuid.UUID(pair.outbound_ref.removeprefix('mail-message:')))
                question, _ = redact_case_text(inbound.subject + '\n' + inbound.body_text)
                answer, _ = redact_case_text(outbound.body_text)
                identifiers = extract_protected(question)
                await session.execute(insert(CaseCandidate).values(
                    id=uuid.uuid4(), email_pair_id=pair.id, user_symptom=question,
                    applicability='Requires human review. Explicit identifiers: ' + ', '.join(identifiers),
                    reply_template=answer, status='candidate',
                    redaction_result={'rules_version': 'text-v1', 'requires_human_review': True}
                ).on_conflict_do_nothing(index_elements=['email_pair_id']))
            job.candidate_count += len(pairs)
            if job.candidate_count == job.paired_count:
                job.stage = 'completed'
                job.status = 'succeeded'
                session.add(AuditEvent(event_type='history_initialization_completed', actor_type='system',
                                       request_id=str(job_id), data={'scanned': job.scanned_count,
                                                                   'candidates': job.candidate_count}))
