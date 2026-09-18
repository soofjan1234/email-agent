"""薄调度器：串行同一 thread，并以 LangGraph checkpoint 判定恢复位置。"""
from contextlib import asynccontextmanager
import hashlib

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from adapters.generator import AgentGenerator
from models import Email
from services.retrieval import RetrievalService
from workflow.graph import build_workflow
from workflow.nodes import SafeDraftProcessor


def workflow_lock_key(thread_id):
    """为 Graph thread 生成稳定且与邮箱锁不同命名空间的 64 位键。"""
    digest = hashlib.blake2b(('email-agent:workflow:' + thread_id).encode(), digest_size=8).digest()
    return int.from_bytes(digest, 'big', signed=True)


@asynccontextmanager
async def locked_workflow(database, thread_id):
    """持有 PostgreSQL 会话锁直至一次 Graph 调用结束，断线自动释放。"""
    async with database.engine.connect() as connection:
        acquired = await connection.scalar(text('SELECT pg_try_advisory_lock(:key)'),
                                           {'key': workflow_lock_key(thread_id)})
        await connection.commit()
        if not acquired:
            yield False
            return
        try:
            yield True
        finally:
            try:
                if not connection.invalidated and not connection.closed:
                    await connection.execute(text('SELECT pg_advisory_unlock(:key)'),
                                             {'key': workflow_lock_key(thread_id)})
                    await connection.commit()
            except Exception:
                await connection.invalidate()


class WorkflowDispatcher:
    """只负责启动、读取和恢复 Graph，不复制节点状态机。"""

    def __init__(self, database, processor=None):
        """默认接入真实检索；生成配置缺失时由节点安全转人工。"""
        self.database = database
        if processor is not None:
            self.processor = processor
        else:
            settings = database.settings
            generator = None
            if settings.generator_base_url and settings.generator_api_key and settings.generator_model:
                generator = AgentGenerator(settings)
            vip_addresses = tuple(item for item in settings.vip_addresses.split(',') if item.strip())
            self.processor = SafeDraftProcessor(RetrievalService(database), generator, vip_addresses)

    def _checkpoint_url(self):
        """把 SQLAlchemy URL 转为 psycopg checkpointer 接受的连接字符串。"""
        url = make_url(self.database.settings.database_url.get_secret_value()).set(drivername='postgresql')
        return url.render_as_string(hide_password=False)

    @asynccontextmanager
    async def _graph(self):
        """每次操作使用独立 checkpointer 连接，避免跨事件循环复用。"""
        async with AsyncPostgresSaver.from_conn_string(self._checkpoint_url()) as saver:
            yield build_workflow(saver, self.processor)

    @staticmethod
    def _config(thread_id):
        """同一业务代次始终复用同一个 LangGraph thread。"""
        return {'configurable': {'thread_id': thread_id}}

    async def _set_projection(self, email_id, values):
        """从 checkpoint 派生查询状态，不用该字段决定 Graph 路由。"""
        phase = values.get('phase')
        status = {'awaiting_review': 'awaiting_review', 'reviewed': 'reviewed',
                  'archived': 'archived'}.get(phase, 'processing')
        async with self.database.session() as session:
            email = await session.get(Email, email_id)
            if email is not None:
                email.status = status
                email.category = values.get('category')
                email.priority = values.get('priority')
                email.risk = values.get('risk')
                decision = values.get('decision') or {}
                email.reply_draft = decision.get('reply_draft')
                email.citations = decision.get('citations', [])

    async def dispatch_email(self, email_id):
        """首次启动邮件 Graph；已有 checkpoint 时只修复投影。"""
        async with self.database.session() as session:
            email = await session.get(Email, email_id)
            if email is None or not email.graph_thread_id:
                raise ValueError('email_not_dispatchable')
            payload = {'email_id': str(email.id), 'workflow_generation': email.workflow_generation,
                       'from_address': email.from_address, 'subject': email.subject,
                       'body_text': email.body_text, 'phase': 'received'}
            thread_id = email.graph_thread_id
        async with locked_workflow(self.database, thread_id) as acquired:
            if not acquired:
                return None
            async with self._graph() as graph:
                snapshot = await graph.aget_state(self._config(thread_id))
                if not snapshot.values:
                    await graph.ainvoke(payload, self._config(thread_id))
                    snapshot = await graph.aget_state(self._config(thread_id))
                await self._set_projection(email_id, snapshot.values)
                return snapshot

    async def get_state(self, email_id):
        """读取最新 checkpoint，供详情和审核入口核对真实中断。"""
        async with self.database.session() as session:
            email = await session.get(Email, email_id)
            if email is None or not email.graph_thread_id:
                return None
            thread_id = email.graph_thread_id
        async with self._graph() as graph:
            return await graph.aget_state(self._config(thread_id))

    async def resume_review(self, email_id, checkpoint_id, review):
        """只在匹配最新人工中断时恢复同一 Graph thread。"""
        async with self.database.session() as session:
            email = await session.get(Email, email_id)
            if email is None or not email.graph_thread_id:
                raise ValueError('email_not_dispatchable')
            thread_id = email.graph_thread_id
        async with locked_workflow(self.database, thread_id) as acquired:
            if not acquired:
                raise RuntimeError('workflow_busy')
            async with self._graph() as graph:
                snapshot = await graph.aget_state(self._config(thread_id))
                current = snapshot.config.get('configurable', {}).get('checkpoint_id') if snapshot.config else None
                if current != checkpoint_id or not snapshot.next:
                    raise ValueError('stale_checkpoint')
                await graph.ainvoke(Command(resume=review), self._config(thread_id))
                resumed = await graph.aget_state(self._config(thread_id))
                await self._set_projection(email_id, resumed.values)
                return resumed

    async def dispatch_pending(self, limit=100):
        """扫描本邮箱业务邮件并幂等启动或修复最多 limit 个 Graph。"""
        prefix = self.database.settings.mailbox_id + ':'
        async with self.database.session() as session:
            ids = list((await session.scalars(select(Email.id).where(
                Email.client_request_id.startswith(prefix),
                Email.status.in_(('received', 'processing', 'awaiting_review'))).order_by(
                Email.created_at, Email.id).limit(limit))).all())
        processed = 0
        for email_id in ids:
            processed += int(await self.dispatch_email(email_id) is not None)
        return processed
