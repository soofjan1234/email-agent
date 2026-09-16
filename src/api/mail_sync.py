"""同步任务查询与增量入口保护；历史模式只能由启动检查创建。"""
from typing import Literal
import uuid

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text

from models import MailSyncJob
from repositories.mail import mailbox_lock_key


router = APIRouter(prefix='/api/v1/mail-sync-jobs', tags=['mail-sync'])


class SyncError(Exception):
    """只携带适合返回客户端的固定错误内容。"""

    def __init__(self, status, code, message):
        """屏蔽底层数据库异常和邮件内容。"""
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


class IncrementalRequest(BaseModel):
    """拒绝历史模式、时间范围及所有未定义字段。"""
    model_config = ConfigDict(extra='forbid')
    sync_request_id: str = Field(min_length=1, max_length=128)
    mode: Literal['incremental']


def error_response(request, status, code, message):
    """返回统一错误结构，不复制未经脱敏的请求值。"""
    return JSONResponse(status_code=status, content={
        'code': code, 'message': message, 'request_id': request.state.request_id})


def serialize_job(job):
    """仅输出任务进度；原文、目录和数据库凭据不进入响应。"""
    return {'id': str(job.id), 'mode': job.mode, 'status': job.status, 'stage': job.stage,
            'scanned_count': job.scanned_count, 'added_count': job.added_count,
            'skipped_count': job.skipped_count, 'failed_count': job.failed_count,
            'initialization_boundary': job.initialization_boundary, 'scan_cursor': job.scan_cursor,
            'pairing_progress': {'count': job.paired_count, 'complete': job.stage in ('candidates', 'completed')},
            'candidate_progress': {'count': job.candidate_count, 'complete': job.stage == 'completed'},
            'unsupported_count': sum(job.unsupported_reasons.values()),
            'unsupported_reasons': job.unsupported_reasons, 'failure_type': job.failure_type,
            'retryable': job.retryable}


@router.get('')
async def list_jobs(request: Request, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                    mode: Literal['historical_backfill', 'incremental'] | None = None,
                    status: Literal['pending', 'running', 'succeeded', 'failed'] | None = None):
    """只查询当前配置邮箱，按创建时间稳定分页。"""
    database = request.app.state.database
    filters = [MailSyncJob.mailbox_id == database.settings.mailbox_id]
    if mode is not None:
        filters.append(MailSyncJob.mode == mode)
    if status is not None:
        filters.append(MailSyncJob.status == status)
    async with database.session() as session:
        total = await session.scalar(select(func.count()).select_from(MailSyncJob).where(*filters))
        jobs = list((await session.scalars(select(MailSyncJob).where(*filters).order_by(
            MailSyncJob.created_at.desc(), MailSyncJob.id).offset((page - 1) * page_size).limit(page_size))).all())
        return {'items': [serialize_job(job) for job in jobs], 'total': total,
                'page': page, 'page_size': page_size}


@router.get('/{job_id}')
async def get_job(job_id: uuid.UUID, request: Request):
    """返回本邮箱的任务详情，其他邮箱标识同样视为不存在。"""
    database = request.app.state.database
    async with database.session() as session:
        job = await session.scalar(select(MailSyncJob).where(
            MailSyncJob.id == job_id, MailSyncJob.mailbox_id == database.settings.mailbox_id))
        if job is None:
            raise SyncError(404, 'not_found', 'Sync job not found')
        return serialize_job(job)


@router.post('', status_code=202)
async def request_incremental(body: IncrementalRequest, request: Request):
    """登记幂等增量任务；实际增量读取与 Graph 调度由 B1 接入。"""
    database = request.app.state.database
    mailbox_id = database.settings.mailbox_id
    async with database.session() as session:
        existing = await session.scalar(select(MailSyncJob).where(
            MailSyncJob.mailbox_id == mailbox_id, MailSyncJob.sync_request_id == body.sync_request_id))
        if existing is not None:
            if existing.mode != body.mode:
                raise SyncError(409, 'idempotency_conflict', 'Request parameters conflict with the existing job')
            return serialize_job(existing)
        locked = await session.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'),
                                      {'key': mailbox_lock_key(mailbox_id)})
        if not locked:
            raise SyncError(409, 'sync_busy', 'Mailbox synchronization is running')
        # 首次查询后另一个 API 进程可能已提交同一请求，取得锁后再次核对。
        existing = await session.scalar(select(MailSyncJob).where(
            MailSyncJob.mailbox_id == mailbox_id, MailSyncJob.sync_request_id == body.sync_request_id))
        if existing is not None:
            if existing.mode != body.mode:
                raise SyncError(409, 'idempotency_conflict', 'Request parameters conflict with the existing job')
            return serialize_job(existing)
        history = await session.scalar(select(MailSyncJob).where(
            MailSyncJob.mailbox_id == mailbox_id, MailSyncJob.mode == 'historical_backfill'))
        if history is None or history.status != 'succeeded':
            raise SyncError(409, 'initialization_incomplete', 'Historical initialization must finish first')
        busy = await session.scalar(select(MailSyncJob.id).where(
            MailSyncJob.mailbox_id == mailbox_id, MailSyncJob.status.in_(('pending', 'running'))).limit(1))
        if busy:
            raise SyncError(409, 'sync_busy', 'Mailbox synchronization is pending or running')
        job = MailSyncJob(mailbox_id=mailbox_id, mode=body.mode, sync_request_id=body.sync_request_id)
        session.add(job)
        await session.flush()
        return serialize_job(job)
