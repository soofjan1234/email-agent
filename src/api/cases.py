"""历史配对确认与知识案例审核接口，与邮件 Graph 审核相互独立。"""
from typing import Annotated, Literal
import uuid

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from api.knowledge import knowledge_service
from models import CaseCandidate, HistoricalEmailPair
from services.knowledge import KnowledgeError, serialize_candidate


router = APIRouter(prefix='/api/v1', tags=['cases'])


class PairConfirmation(BaseModel):
    """仅确认或拒绝已有确定关系，不能修改源邮件标识。"""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    action: Literal['confirm', 'reject']
    reviewer: str = Field(min_length=1, max_length=128)


class ReviewRequest(BaseModel):
    """人工修订必须携带所见版本，避免并发页面互相覆盖。"""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    action: Literal['approve', 'reject']
    reviewer: str = Field(min_length=1, max_length=128)
    user_symptom: str = Field(default='', max_length=100000)
    applicability: str = Field(default='', max_length=100000)
    reply_template: str = Field(default='', max_length=100000)
    fact_sources: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(default_factory=list, max_length=100)
    product_model: str | None = Field(default=None, max_length=128)
    os_version: str | None = Field(default=None, max_length=128)
    category: str | None = Field(default=None, max_length=128)
    risk_tags: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(default_factory=list, max_length=100)
    comment: str = Field(default='', max_length=10000)


class PublishRequest(BaseModel):
    """发布只引用已审核版本，不能顺便替换正文。"""
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1)


class ArchiveRequest(PublishRequest):
    """归档必须携带操作者、所见审核版本和已发布文档快照。"""
    # 页面未见已发布文档时显式提交 null，缺失字段则拒绝旧调用方。
    expected_published_document_id: uuid.UUID | None = Field(...)
    reviewer: str = Field(min_length=1, max_length=128)


def candidate_scope(database):
    """历史候选按邮箱隔离，系统回复候选由未来 B 阶段接入。"""
    pair_ids = select(HistoricalEmailPair.id).where(
        HistoricalEmailPair.mailbox_id == database.settings.mailbox_id)
    return or_(CaseCandidate.email_pair_id.is_(None), CaseCandidate.email_pair_id.in_(pair_ids))


@router.get('/case-pairs')
async def list_pairs(request: Request, sync_job_id: uuid.UUID | None = None,
                     status: Literal['paired', 'needs_review', 'rejected'] | None = None,
                     page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    """查询确定一对一结果，不公开邮件原文和存储路径。"""
    database = request.app.state.database
    filters = [HistoricalEmailPair.mailbox_id == database.settings.mailbox_id]
    if sync_job_id is not None:
        filters.append(HistoricalEmailPair.sync_job_id == sync_job_id)
    if status:
        filters.append(HistoricalEmailPair.status == status)
    async with database.session() as session:
        total = await session.scalar(select(func.count()).select_from(HistoricalEmailPair).where(*filters))
        pairs = (await session.scalars(select(HistoricalEmailPair).where(*filters).order_by(
            HistoricalEmailPair.created_at.desc(), HistoricalEmailPair.id).offset((page - 1) * page_size).limit(page_size))).all()
        return {'items': [{'id': str(pair.id), 'status': pair.status, 'pairing_method': pair.pairing_method,
                           'pairing_confidence': pair.pairing_confidence,
                           'sync_job_id': str(pair.sync_job_id) if pair.sync_job_id else None} for pair in pairs],
                'total': total, 'page': page, 'page_size': page_size}


@router.post('/case-pairs/{pair_id}/confirm')
async def confirm_pair(pair_id: uuid.UUID, body: PairConfirmation, request: Request):
    """确认复用 A2 候选；拒绝同步撤销未发布候选。"""
    return await knowledge_service(request).confirm_pair(pair_id, body.action, body.reviewer)


@router.get('/case-candidates')
async def list_candidates(request: Request,
                          status: Literal['candidate', 'reviewed', 'active', 'rejected', 'archived'] | None = None,
                          page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    """按状态分页查询脱敏候选。"""
    database = request.app.state.database
    filters = [candidate_scope(database)]
    if status:
        filters.append(CaseCandidate.status == status)
    async with database.session() as session:
        total = await session.scalar(select(func.count()).select_from(CaseCandidate).where(*filters))
        candidates = (await session.scalars(select(CaseCandidate).where(*filters).order_by(
            CaseCandidate.created_at.desc(), CaseCandidate.id).offset((page - 1) * page_size).limit(page_size))).all()
        return {'items': [serialize_candidate(candidate) for candidate in candidates],
                'total': total, 'page': page, 'page_size': page_size}


@router.get('/case-candidates/{candidate_id}')
async def get_candidate(candidate_id: uuid.UUID, request: Request):
    """详情只返回清洗审核字段，不暴露 raw_review 或邮件原文。"""
    database = request.app.state.database
    async with database.session() as session:
        candidate = await session.scalar(select(CaseCandidate).where(
            CaseCandidate.id == candidate_id, candidate_scope(database)))
        if candidate is None:
            raise KnowledgeError(404, 'not_found', 'Candidate not found')
        return serialize_candidate(candidate)


@router.post('/case-candidates/{candidate_id}/review')
async def review_candidate(candidate_id: uuid.UUID, body: ReviewRequest, request: Request):
    """保存事实来源、脱敏结果及人工修订。"""
    return await knowledge_service(request).review(candidate_id, body.model_dump())


@router.post('/case-candidates/{candidate_id}/publish')
async def publish_candidate(candidate_id: uuid.UUID, body: PublishRequest, request: Request):
    """仅发布完整审核版本，错误响应不包含模型内容。"""
    return await knowledge_service(request).publish(candidate_id, body.expected_revision)


@router.post('/case-candidates/{candidate_id}/archive')
async def archive_candidate(candidate_id: uuid.UUID, body: ArchiveRequest, request: Request):
    """撤销检索资格但保留引用。"""
    return await knowledge_service(request).archive(
        candidate_id, body.expected_revision, body.expected_published_document_id, body.reviewer)
