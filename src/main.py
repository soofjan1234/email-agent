"""API 入口：启动登记历史初始化，后台扫描由独立 worker 执行。"""
from contextlib import asynccontextmanager
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from api.mail_sync import SyncError, error_response, router
from config import Settings
from db import Database
from services.mail_sync import MailSyncService
from api.cases import router as cases_router
from api.emails import router as emails_router
from api.reviews import router as reviews_router
from api.outbox import router as outbox_router
from api.knowledge import router as knowledge_router
from services.knowledge import KnowledgeError
from services.reviews import ReviewError

def create_app(settings=None):
    """通过 lifespan 管理连接池，启动失败时不提供假就绪状态。"""
    @asynccontextmanager
    async def lifespan(app):
        """数据库迁移和身份可用后才接受请求，退出时释放连接。"""
        database = Database(settings or Settings())
        app.state.database = database
        try:
            await database.check_ready()
            await MailSyncService(database).ensure_initialization()
            yield
        finally:
            await database.close()

    app = FastAPI(title='Email Agent', lifespan=lifespan)
    app.include_router(router)
    app.include_router(cases_router)
    app.include_router(knowledge_router)
    app.include_router(emails_router)
    app.include_router(reviews_router)
    app.include_router(outbox_router)

    @app.middleware('http')
    async def identify_request(request, call_next):
        """为请求关联错误与后续审计，不记录邮件正文。"""
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        """按既定 API 契约返回 400，不回显敏感参数。"""
        return error_response(request, 400, 'invalid_request', 'Invalid request parameters')

    @app.exception_handler(SyncError)
    @app.exception_handler(KnowledgeError)
    @app.exception_handler(ReviewError)
    async def sync_error(request, exc):
        """把领域状态冲突转换为统一 HTTP 错误。"""
        return error_response(request, exc.status, exc.code, exc.message)

    @app.get('/health')
    async def health():
        """检查真实依赖，响应与错误均不暴露连接信息。"""
        try:
            await app.state.database.check_ready()
        except Exception:
            raise HTTPException(status_code=503, detail='database unavailable') from None
        return {'status': 'ok'}

    return app


app = create_app()
