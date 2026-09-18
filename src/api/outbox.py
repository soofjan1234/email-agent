"""只读模拟发件箱 API；不存在任何 SMTP 调用。"""
import uuid

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from api.mail_sync import SyncError
from models import Email, SimulatedOutbox


router = APIRouter(prefix='/api/v1/outbox', tags=['outbox'])


def serialize_outbox(row):
    """返回模拟发件记录及唯一审核来源。"""
    return {'id': str(row.id), 'email_id': str(row.email_id), 'review_id': str(row.review_id),
            'to_address': row.to_address, 'subject': row.subject, 'body_text': row.body_text,
            'sent_at': row.sent_at.isoformat() if row.sent_at else None}


@router.get('')
async def list_outbox(request: Request, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    """仅查询当前配置邮箱产生的模拟发件。"""
    prefix = request.app.state.database.settings.mailbox_id + ':'
    scope = SimulatedOutbox.email_id.in_(select(Email.id).where(Email.client_request_id.startswith(prefix)))
    async with request.app.state.database.session() as session:
        total = await session.scalar(select(func.count()).select_from(SimulatedOutbox).where(scope))
        rows = list((await session.scalars(select(SimulatedOutbox).where(scope).order_by(
            SimulatedOutbox.created_at.desc(), SimulatedOutbox.id).offset(
            (page - 1) * page_size).limit(page_size))).all())
        return {'items': [serialize_outbox(row) for row in rows], 'total': total,
                'page': page, 'page_size': page_size}


@router.get('/{outbox_id}')
async def get_outbox(outbox_id: uuid.UUID, request: Request):
    """按 ID 查询当前邮箱模拟发件。"""
    prefix = request.app.state.database.settings.mailbox_id + ':'
    async with request.app.state.database.session() as session:
        row = await session.scalar(select(SimulatedOutbox).join(Email).where(
            SimulatedOutbox.id == outbox_id, Email.client_request_id.startswith(prefix)))
        if row is None:
            raise SyncError(404, 'not_found', 'Outbox item not found')
        return serialize_outbox(row)
