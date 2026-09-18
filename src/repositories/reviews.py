"""B3 审核、模拟发件和候选的幂等数据库写入。"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from evals.harness.redact import redact_case_text
from models import AuditEvent, CaseCandidate, Email, Review, SimulatedOutbox


async def apply_review_effects(session, review, decision):
    """一次事务补齐审核副作用；重复调用按 review 唯一键复用事实。"""
    if review.result_applied_at is not None:
        return
    email = await session.get(Email, review.email_id, with_for_update=True)
    approved = review.action in ('approve', 'edit_and_approve')
    if approved:
        await session.execute(insert(SimulatedOutbox).values(
            email_id=email.id, review_id=review.id, to_address=email.from_address,
            subject='Re: ' + email.subject, body_text=review.final_content).on_conflict_do_nothing(
            index_elements=['review_id']))
        symptom, _ = redact_case_text(email.subject + '\n' + email.body_text)
        template, redaction = redact_case_text(review.final_content)
        await session.execute(insert(CaseCandidate).values(
            email_id=email.id, review_id=review.id,
            user_symptom=symptom,
            applicability='Requires human review before knowledge publication.',
            reply_template=template, category=review.classification,
            risk_tags=[review.risk] if review.risk and review.risk != 'none' else [],
            redaction_result={'rules_version': 'text-v1', 'requires_human_review': True,
                              'changed': bool(redaction)}, status='candidate').on_conflict_do_nothing(
            index_elements=['review_id']))
        email.status = 'completed'
    elif review.action == 'reject':
        email.status = 'rejected'
    else:
        email.status = 'manual_review'
    review.result_applied_at = datetime.now(timezone.utc)
    session.add(AuditEvent(email_id=email.id, request_id=review.review_request_id,
        graph_thread_id=review.graph_thread_id, checkpoint_id=review.checkpoint_id,
        event_type='review_effects_applied', actor_type='system', data={'action': review.action}))


async def find_review_by_request(session, request_id):
    """按客户端幂等键读取已有人工决定。"""
    return await session.scalar(select(Review).where(Review.review_request_id == request_id))
