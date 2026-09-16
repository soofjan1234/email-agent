"""A2 用真实数据库验证快照、恢复、并发与入口保护。"""
import shutil
import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import func, select

from adapters.mailbox import MockMailboxAdapter
from main import create_app
from models import CaseCandidate, Email, HistoricalEmailPair, KnowledgeDocument, MailMessage, MailSource, MailSyncJob
from repositories.mail import locked_mailbox
from services.mail_sync import MailSyncService


def seed_mailbox(root):
    """复制脱敏公开夹具，测试只读自己的临时邮箱。"""
    fixtures = Path(__file__).resolve().parents[1] / 'fixtures/mailbox'
    for folder in ('inbox', 'sent'):
        for path in (fixtures / folder).glob('*.eml'):
            shutil.copyfile(path, root / folder / path.name)


async def test_history_snapshot_and_candidates(database):
    """全量识别跨批次关系，候选脱敏且历史邮件不进入新邮件表。"""
    root = database.settings.mailbox_root
    seed_mailbox(root)
    async with database.session() as session:
        original_emails = await session.scalar(select(func.count()).select_from(Email))
        original_knowledge = await session.scalar(select(func.count()).select_from(KnowledgeDocument))
    service = MailSyncService(database, MockMailboxAdapter(root), page_size=1)
    job_id = await service.ensure_initialization()
    assert await service.run_history()
    assert not await service.run_history()
    assert await service.ensure_initialization() == job_id
    async with database.session() as session:
        job = await session.get(MailSyncJob, job_id)
        assert job.status == 'succeeded'
        assert job.scanned_count == 7
        assert job.added_count == 6 and job.skipped_count == 1
        assert job.candidate_count == 1 and job.paired_count == 1
        assert job.unsupported_reasons == {'complex_relationship': 3, 'unmatched': 1}
        assert await session.scalar(select(func.count()).select_from(Email)) == original_emails
        assert await session.scalar(select(func.count()).select_from(KnowledgeDocument)) == original_knowledge
        candidates = list((await session.scalars(select(CaseCandidate).join(HistoricalEmailPair).where(
            HistoricalEmailPair.sync_job_id == job_id))).all())
        assert len(candidates) == 1 and candidates[0].status == 'candidate'
        assert 'alice@example.test' not in candidates[0].user_symptom
        assert '[email]' in candidates[0].user_symptom
        assert 'SMB' in candidates[0].user_symptom


async def test_snapshot_survives_source_changes_and_new_mail(database):
    """快照固定后新增文件不进入历史任务，已快照原文不因文件变化丢失。"""
    root = database.settings.mailbox_root
    seed_mailbox(root)
    adapter = MockMailboxAdapter(root)
    service = MailSyncService(database, adapter, page_size=1)
    job_id = await service.ensure_initialization()
    await service.run_history(max_pages=1)
    (root / 'inbox/01-question.eml').write_text('changed after snapshot', encoding='utf-8')
    (root / 'inbox/new.eml').write_text('Message-ID: <new@example.test>\n\nnew', encoding='utf-8')
    assert await service.run_history()
    async with database.session() as session:
        job = await session.get(MailSyncJob, job_id)
        assert job.scanned_count == 7 and job.candidate_count == 1
        messages = list((await session.scalars(select(MailMessage).where(MailMessage.sync_job_id == job_id))).all())
        assert not any(message.message_id == '<new@example.test>' for message in messages)
        assert any('alice@example.test' in message.body_text for message in messages)


async def test_empty_mailbox_succeeds(database):
    """空的两个目录也是完整初始化，重启不会重复创建任务。"""
    service = MailSyncService(database, MockMailboxAdapter(database.settings.mailbox_root))
    job_id = await service.ensure_initialization()
    await service.run_history()
    async with database.session() as session:
        job = await session.get(MailSyncJob, job_id)
        assert job.status == 'succeeded' and job.scanned_count == 0


async def test_api_initialization_guard_and_job_visibility(database):
    """启动创建可查询任务；初始化完成前拒绝增量，非法历史请求返回 400。"""
    app = create_app(database.settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            jobs = (await client.get('/api/v1/mail-sync-jobs')).json()
            assert jobs['total'] == 1
            job_id = jobs['items'][0]['id']
            detail = await client.get(f'/api/v1/mail-sync-jobs/{job_id}')
            assert detail.status_code == 200 and detail.json()['mode'] == 'historical_backfill'
            request = {'sync_request_id': str(uuid.uuid4()), 'mode': 'incremental'}
            blocked = await client.post('/api/v1/mail-sync-jobs', json=request)
            assert blocked.status_code == 409 and blocked.json()['request_id']
            for patch in ({'mode': 'historical_backfill'}, {'start_time': '2026-01-01'}, {'end_time': '2026-01-02'}):
                assert (await client.post('/api/v1/mail-sync-jobs', json=request | patch)).status_code == 400
            assert (await client.get(f'/api/v1/mail-sync-jobs/{uuid.uuid4()}')).status_code == 404
            assert (await client.get('/api/v1/mail-sync-jobs?page=0')).status_code == 400
            service = MailSyncService(database, MockMailboxAdapter(database.settings.mailbox_root))
            await service.run_history()
            accepted = await client.post('/api/v1/mail-sync-jobs', json=request)
            replay = await client.post('/api/v1/mail-sync-jobs', json=request)
            assert accepted.status_code == 202 and replay.json()['id'] == accepted.json()['id']
            assert (await client.post('/api/v1/mail-sync-jobs', json=request | {
                'sync_request_id': str(uuid.uuid4())})).status_code == 409


def process_environment(database):
    """子进程只继承显式测试数据库与本测试专属邮箱。"""
    root = Path(__file__).resolve().parents[2]
    return dict(os.environ, DATABASE_URL=database.settings.database_url.get_secret_value(),
                MAILBOX_ID=database.settings.mailbox_id, MAILBOX_ROOT=str(database.settings.mailbox_root),
                PYTHONPATH=os.pathsep.join((str(root / 'src'), str(root))))


def run_child(database, *arguments):
    """以真实进程调用故障注入工具，避免仅靠同进程异常模拟崩溃。"""
    root = Path(__file__).resolve().parents[2]
    return subprocess.run([sys.executable, 'tests/helpers/history_worker.py', *arguments],
                          cwd=root, env=process_environment(database), capture_output=True, timeout=30)


async def test_process_crash_rolls_back_uncommitted_mail_and_resumes(database):
    """第一页提交后，第二页写邮件但未提交游标时硬退出；新进程无遗漏恢复。"""
    seed_mailbox(database.settings.mailbox_root)
    crashed = await asyncio.to_thread(run_child, database, '--crash-after-page', '2')
    assert crashed.returncode == 23, crashed.stderr.decode('utf-8', errors='replace')
    async with database.session() as session:
        job = await session.scalar(select(MailSyncJob).where(MailSyncJob.mailbox_id == database.settings.mailbox_id))
        assert job.scanned_count == 1 and job.stage == 'scanning'
        assert await session.scalar(select(func.count()).select_from(MailMessage).where(
            MailMessage.sync_job_id == job.id)) == 1
        job_id = job.id
    resumed = await asyncio.to_thread(run_child, database)
    assert resumed.returncode == 0, resumed.stderr.decode('utf-8', errors='replace')
    async with database.session() as session:
        job = await session.get(MailSyncJob, job_id)
        assert job.status == 'succeeded' and job.scanned_count == 7 and job.candidate_count == 1
        assert await session.scalar(select(func.count()).select_from(MailMessage).where(
            MailMessage.sync_job_id == job_id)) == 6


async def test_two_processes_only_initialize_mailbox_once(database):
    """两个 worker 同时启动，只留下一个任务、一份快照和一份候选。"""
    seed_mailbox(database.settings.mailbox_root)
    results = await asyncio.gather(*[
        asyncio.to_thread(run_child, database, '--snapshot-delay', '1') for _ in range(2)])
    assert all(result.returncode == 0 for result in results)
    assert sum(json.loads(result.stdout)['processed'] for result in results) == 1
    async with database.session() as session:
        jobs = list((await session.scalars(select(MailSyncJob).where(
            MailSyncJob.mailbox_id == database.settings.mailbox_id))).all())
        assert len(jobs) == 1 and jobs[0].candidate_count == 1
        assert await session.scalar(select(func.count()).select_from(MailSource).where(
            MailSource.sync_job_id == jobs[0].id)) == 7


async def test_other_process_cannot_work_while_mailbox_locked(database):
    """显式持锁时，新进程必须跳过，API 的增量入口也不能越过锁。"""
    service = MailSyncService(database)
    await service.ensure_initialization()
    async with locked_mailbox(database, database.settings.mailbox_id) as session:
        assert session is not None
        child = await asyncio.to_thread(run_child, database)
        assert child.returncode == 0 and json.loads(child.stdout)['processed'] is False


async def test_source_failure_is_queryable_and_retryable(database):
    """错误路径不能被当作空邮箱成功；修复数据源后从原任务继续。"""
    root = database.settings.mailbox_root
    (root / 'sent').rmdir()
    service = MailSyncService(database)
    job_id = await service.ensure_initialization()
    with pytest.raises(ValueError, match='mailbox_unavailable'):
        await service.run_history()
    async with database.session() as session:
        job = await session.get(MailSyncJob, job_id)
        assert job.status == 'failed' and job.retryable and job.failure_type == 'source_unavailable'
        assert job.initialization_boundary is None
    (root / 'sent').mkdir()
    await service.run_history()
    async with database.session() as session:
        job = await session.get(MailSyncJob, job_id)
        assert job.status == 'succeeded' and job.failure_type is None and not job.retryable


async def test_duplicate_message_id_with_different_content_is_not_deduplicated(database):
    """相同 ID 不同原文全部保留，并排除受影响会话，不能静默丢弃。"""
    root = database.settings.mailbox_root
    seed_mailbox(root)
    changed = (root / 'inbox/01-question.eml').read_bytes() + b'\nDifferent body.\n'
    (root / 'inbox/collision.eml').write_bytes(changed)
    service = MailSyncService(database, page_size=1)
    job_id = await service.ensure_initialization()
    await service.run_history()
    async with database.session() as session:
        job = await session.get(MailSyncJob, job_id)
        assert job.added_count == 7 and job.skipped_count == 1 and job.candidate_count == 0
        assert job.unsupported_reasons['duplicate_message_id'] == 3


async def test_disconnected_worker_does_not_reconnect_to_mark_job_failed(database):
    """锁连接失效后旧执行者不再写状态，新连接可以安全接管已提交进度。"""
    class DisconnectingService(MailSyncService):
        """在第一页完成后模拟锁连接失效。"""

        async def _scan_page(self, session, job_id):
            """只丢弃当前测试连接，不停止本机 PostgreSQL。"""
            await super()._scan_page(session, job_id)
            await session.bind.invalidate()
            raise ConnectionError('test connection lost')

    service = DisconnectingService(database)
    job_id = await service.ensure_initialization()
    with pytest.raises(ConnectionError):
        await service.run_history()
    async with database.session() as session:
        job = await session.get(MailSyncJob, job_id)
        assert job.status == 'running' and job.failure_type is None
    assert await MailSyncService(database).run_history()


async def test_error_after_successful_commit_does_not_revert_success(database):
    """完成事实以已提交数据库为准，提交后的异常不得覆盖成功状态。"""
    class AfterCommitFailure(MailSyncService):
        """在最终事务成功后注入异常。"""

        async def _candidates(self, session, job_id):
            """保留真实事务提交，再模拟调用方失败。"""
            await super()._candidates(session, job_id)
            raise RuntimeError('test failure after commit')

    service = AfterCommitFailure(database)
    job_id = await service.ensure_initialization()
    with pytest.raises(RuntimeError):
        await service.run_history()
    async with database.session() as session:
        job = await session.get(MailSyncJob, job_id)
        assert job.status == 'succeeded' and job.failure_type is None
    assert not await MailSyncService(database).run_history()
