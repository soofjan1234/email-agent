"""B3 审核事务、Graph 恢复和副作用补偿。"""
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from models import AuditEvent, Email, Review
from repositories.reviews import apply_review_effects, find_review_by_request
from services.dispatch import WorkflowDispatcher


class ReviewError(Exception):
    """可安全映射为 HTTP 的审核领域错误。"""

    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


def serialize_review(review):
    """返回审核身份和完成状态，不公开受控原始审计字段。"""
    return {'id': str(review.id), 'email_id': str(review.email_id), 'action': review.action,
            'review_request_id': review.review_request_id, 'graph_thread_id': review.graph_thread_id,
            'checkpoint_id': review.checkpoint_id, 'final_content': review.final_content,
            'completed': review.result_applied_at is not None}


class ReviewService:
    """先幂等保存人工事实，再恢复 Graph，最后补齐唯一业务副作用。"""

    def __init__(self, database, dispatcher=None):
        self.database = database
        self.dispatcher = dispatcher or WorkflowDispatcher(database)

    @staticmethod
    def _same_request(review, email_id, payload):
        """相同幂等键只允许完全相同的审核目标和动作。"""
        return (review.email_id == email_id and review.graph_thread_id == payload['graph_thread_id']
                and review.checkpoint_id == payload['checkpoint_id'] and review.action == payload['action'])

    async def _load_email(self, email_id):
        """限制审核只能访问当前配置邮箱的业务邮件。"""
        async with self.database.session() as session:
            email = await session.get(Email, email_id)
            if email is None or not email.client_request_id.startswith(self.database.settings.mailbox_id + ':'):
                raise ReviewError(404, 'not_found', 'Email not found')
            return email

    async def submit(self, email_id, payload):
        """保存或重放一次审核，并补偿恢复前后的任意中断。"""
        email = await self._load_email(email_id)
        async with self.database.session() as session:
            existing = await find_review_by_request(session, payload['review_request_id'])
        if existing is not None and not self._same_request(existing, email_id, payload):
            raise ReviewError(409, 'idempotency_conflict', 'Review request conflicts with existing review')

        snapshot = await self.dispatcher.get_state(email_id)
        if existing is None:
            current = snapshot.config.get('configurable', {}).get('checkpoint_id') if snapshot else None
            if (snapshot is None or current != payload['checkpoint_id'] or not snapshot.next
                    or email.graph_thread_id != payload['graph_thread_id']):
                raise ReviewError(409, 'stale_checkpoint', 'Review does not match the current interrupt')
            decision = snapshot.values.get('decision') or {}
            original = decision.get('reply_draft', '')
            final = payload.get('final_content')
            if payload['action'] == 'approve':
                final = original
            if payload['action'] == 'edit_and_approve' and not (final or '').strip():
                raise ReviewError(400, 'invalid_review', 'Edited approval requires final content')
            values = {'id': uuid.uuid4(), 'email_id': email_id,
                'graph_thread_id': payload['graph_thread_id'], 'checkpoint_id': payload['checkpoint_id'],
                'review_request_id': payload['review_request_id'], 'action': payload['action'],
                'original_draft': original, 'final_content': final, 'citations': decision.get('citations', []),
                'model_version': self.database.settings.generator_model or 'safe-fallback',
                'prompt_version': 'b2-v1', 'classification': snapshot.values.get('category', 'other'),
                'priority': snapshot.values.get('priority', 'normal'),
                'risk': snapshot.values.get('risk', 'unknown'), 'reviewer': payload['reviewer'],
                'comment': payload.get('comment')}
            async with self.database.session() as session:
                inserted = await session.scalar(insert(Review).values(**values).on_conflict_do_nothing().returning(
                    Review.id))
                if inserted is None:
                    existing = await find_review_by_request(session, payload['review_request_id'])
                    if existing is None or not self._same_request(existing, email_id, payload):
                        raise ReviewError(409, 'review_conflict', 'Interrupt already has another review')
                else:
                    existing = await session.get(Review, inserted)
                    session.add(AuditEvent(email_id=email_id, request_id=payload['review_request_id'],
                        graph_thread_id=email.graph_thread_id, checkpoint_id=payload['checkpoint_id'],
                        event_type='review_recorded', actor_type='human',
                        data={'action': payload['action'], 'reviewer': payload['reviewer']}))

        # 审核事实提交后才恢复；失败时同一请求可安全补做。
        snapshot = await self.dispatcher.get_state(email_id)
        if snapshot and snapshot.next:
            try:
                await self.dispatcher.resume_review(email_id, existing.checkpoint_id,
                    {'review_id': str(existing.id), 'action': existing.action})
            except (ValueError, RuntimeError) as exc:
                raise ReviewError(409, 'resume_conflict', 'Workflow could not resume from this review') from exc
        decision = snapshot.values.get('decision') if snapshot else {}
        async with self.database.session() as session:
            review = await session.get(Review, existing.id, with_for_update=True)
            await apply_review_effects(session, review, decision or {})
        async with self.database.session() as session:
            return serialize_review(await session.get(Review, existing.id))
