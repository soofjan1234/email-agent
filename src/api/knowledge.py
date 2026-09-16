"""本地产品知识导入接口，服务端配置决定可信目录与模型。"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from services.knowledge import KnowledgeService


router = APIRouter(prefix='/api/v1/knowledge', tags=['knowledge'])


class ImportRequest(BaseModel):
    """只接收相对路径及显式适用范围，不接收文件系统根目录和模型配置。"""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    path: str = Field(min_length=1, max_length=512)
    title: str | None = Field(default=None, min_length=1, max_length=256)
    product_model: str | None = Field(default=None, max_length=128)
    os_version: str | None = Field(default=None, max_length=128)
    category: str | None = Field(default=None, max_length=128)


def knowledge_service(request):
    """为当前请求绑定审计标识；模型替身只通过应用构造注入，不由 HTTP 选择。"""
    return KnowledgeService(request.app.state.database,
                            embedding_factory=getattr(request.app.state, 'embedding_factory', None),
                            request_id=request.state.request_id)


@router.post('/import')
async def import_knowledge(body: ImportRequest, request: Request):
    """同步返回完整有效版本；失败可重试且不返回文件内容。"""
    return await knowledge_service(request).import_document(**body.model_dump())
