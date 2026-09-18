"""邮件查询 API：状态只展示 checkpoint 投影，不接受强制推进。"""
import uuid

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from api.mail_sync import SyncError
from models import Email
from services.dispatch import WorkflowDispatcher


router = APIRouter(prefix='/api/v1/emails', tags=['emails'])


def serialize_email(email):
    """返回审核所需邮件字段，不包含凭据或底层存储位置。"""
    return {'id': str(email.id), 'from_address': email.from_address, 'subject': email.subject,
            'body_text': email.body_text, 'status': email.status,
            'category': email.category, 'priority': email.priority, 'risk': email.risk,
            'reply_draft': email.reply_draft, 'citations': email.citations,
            'graph_thread_id': email.graph_thread_id,
            'workflow_generation': email.workflow_generation}


@router.get('')
async def list_emails(request: Request, page: int = Query(1, ge=1),
                      page_size: int = Query(20, ge=1, le=100), status: str | None = None,
                      category: str | None = None, priority: str | None = None):
    """只列出当前邮箱来源的业务邮件并稳定分页。"""
    prefix = request.app.state.database.settings.mailbox_id + ':'
    filters = [Email.client_request_id.startswith(prefix)]
    if status:
        filters.append(Email.status == status)
    if category:
        filters.append(Email.category == category)
    if priority:
        filters.append(Email.priority == priority)
    async with request.app.state.database.session() as session:
        total = await session.scalar(select(func.count()).select_from(Email).where(*filters))
        rows = list((await session.scalars(select(Email).where(*filters).order_by(
            Email.created_at.desc(), Email.id).offset((page - 1) * page_size).limit(page_size))).all())
        return {'items': [serialize_email(email) for email in rows], 'total': total,
                'page': page, 'page_size': page_size}


@router.get('/{email_id}')
async def get_email(email_id: uuid.UUID, request: Request):
    """返回邮件及最新 checkpoint 中的可审核决定。"""
    database = request.app.state.database
    async with database.session() as session:
        email = await session.get(Email, email_id)
        if email is None or not email.client_request_id.startswith(database.settings.mailbox_id + ':'):
            raise SyncError(404, 'not_found', 'Email not found')
        result = serialize_email(email)
    snapshot = await WorkflowDispatcher(database).get_state(email_id)
    if snapshot and snapshot.values:
        result['decision'] = snapshot.values.get('decision')
        result['checkpoint_id'] = snapshot.config.get('configurable', {}).get('checkpoint_id')
    return result
