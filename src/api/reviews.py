"""B3 人工审核 API。"""
from typing import Literal
import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.reviews import ReviewService


router = APIRouter(prefix='/api/v1/emails', tags=['reviews'])


class ReviewRequest(BaseModel):
    """审核必须携带页面看到的 thread 与 checkpoint 快照。"""
    model_config = ConfigDict(extra='forbid')
    review_request_id: str = Field(min_length=1, max_length=128)
    graph_thread_id: str = Field(min_length=1, max_length=256)
    checkpoint_id: str = Field(min_length=1, max_length=256)
    action: Literal['approve', 'edit_and_approve', 'reject', 'manual_review']
    final_content: str | None = Field(default=None, max_length=100_000)
    reviewer: str = Field(min_length=1, max_length=128)
    comment: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode='after')
    def require_edited_content(self):
        """编辑批准必须明确提交最终文本。"""
        if self.action == 'edit_and_approve' and not (self.final_content or '').strip():
            raise ValueError('final_content is required')
        return self


@router.post('/{email_id}/reviews')
async def submit_review(email_id: uuid.UUID, body: ReviewRequest, request: Request):
    """保存人工事实并从匹配中断恢复，重复请求会补齐未完成步骤。"""
    return await ReviewService(request.app.state.database).submit(email_id, body.model_dump())
