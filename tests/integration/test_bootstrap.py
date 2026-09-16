"""A1 在真实 PostgreSQL 上验证迁移、业务持久化与启动。"""
import uuid
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from main import create_app
from models import AuditEvent, Email
from worker import run_once


async def test_mail_roundtrip_and_duplicate_rejected(database):
    """邮件和审计真实落库，重复请求在数据库层被拒绝。"""
    request_id = str(uuid.uuid4())
    async with database.session() as session:
        email = Email(client_request_id=request_id, from_address='sample@example.test',
                      subject='NAS help', body_text='Cannot connect')
        session.add(email)
        await session.flush()
        session.add(AuditEvent(email_id=email.id, request_id=request_id,
                               event_type='bootstrap_test', actor_type='system', data={}))
    async with database.session() as session:
        found = await session.scalar(select(Email).where(Email.client_request_id == request_id))
        assert found.body_text == 'Cannot connect'
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.email_id == found.id)) == 1
    with pytest.raises(IntegrityError):
        async with database.session() as session:
            session.add(Email(client_request_id=request_id, from_address='sample@example.test',
                              subject='duplicate', body_text='duplicate'))


async def test_api_and_worker_start_with_migrated_database(database):
    """API 与 worker 都检查同一迁移及模型身份，不自动建表。"""
    app = create_app(database.settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get('/health')
            assert response.status_code == 200
            assert response.json() == {'status': 'ok'}
    await run_once(database.settings)
    async with database.session() as session:
        assert await session.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
        assert await session.scalar(text('SELECT version_num FROM alembic_version')) == '0003_knowledge'


async def test_root_commands_start_real_processes(database, tmp_path):
    """从仓库根目录验证实际进程命令，不依赖 pytest 注入的导入路径。"""
    root = Path(__file__).resolve().parents[2]
    environment = dict(os.environ, PYTHONPATH=str(root / 'src'),
                       DATABASE_URL=database.settings.database_url.get_secret_value(),
                       MAILBOX_ID=database.settings.mailbox_id, MAILBOX_ROOT=str(database.settings.mailbox_root))
    completed = subprocess.run([sys.executable, '-m', 'worker', '--once'], cwd=root,
                               env=environment, capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stderr.decode('utf-8', errors='replace')
    # 动态端口隔离本机已有服务；临时日志只供本次失败诊断。
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    with (tmp_path / 'api.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'main:app', '--app-dir', 'src',
             '--loop', 'asyncio:SelectorEventLoop', '--host', '127.0.0.1', '--port', str(port)],
            cwd=root, env=environment, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            with httpx.Client(trust_env=False, timeout=1) as client:
                while time.monotonic() < deadline:
                    assert process.poll() is None, 'API exited before becoming ready'
                    try:
                        response = client.get(f'http://127.0.0.1:{port}/health')
                        assert response.status_code == 200
                        break
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        time.sleep(0.1)
                else:
                    pytest.fail('API readiness timed out')
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
