"""本地产品知识导入接口，服务端配置决定可信目录与模型。"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from services.knowledge import KnowledgeError, KnowledgeService


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
    """只在显式开发开关下读取服务端受控目录，避免 HTTP 请求选择本机路径。"""
    # 1. 生产默认拒绝路径导入；后续页面上传必须提交文件内容而非 path。
    if not request.app.state.database.settings.knowledge_local_import_enabled:
        raise KnowledgeError(403, 'local_import_disabled',
                             'Local-path knowledge import is disabled')
    # 2. 开关开启后仍由服务层校验可信根、链接、大小和编码。
    return await knowledge_service(request).import_document(**body.model_dump())
