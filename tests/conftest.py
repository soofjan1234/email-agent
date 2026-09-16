"""集成测试使用显式独立数据库；既有离线评测不依赖 PostgreSQL。"""
import asyncio
import sys
import uuid

import pytest


def pytest_asyncio_loop_factories(config, item):
    """原生 Windows 的 psycopg 使用 Selector 事件循环。"""
    if sys.platform == 'win32':
        return {'selector': asyncio.SelectorEventLoop}
    return {'default': asyncio.new_event_loop}


@pytest.fixture
async def database(tmp_path):
    """迁移独立测试库且不清表，唯一测试数据避免破坏已有内容。"""
    from alembic import command
    from alembic.config import Config
    from config import Settings, validate_test_database
    from db import Database

    settings = Settings()
    if not settings.test_database_url:
        pytest.fail('TEST_DATABASE_URL must explicitly name an independent PostgreSQL test database')
    test_url = settings.test_database_url.get_secret_value()
    validate_test_database(settings.database_url.get_secret_value(), test_url)
    mailbox = tmp_path / 'mailbox'
    for folder in ('inbox', 'sent'):
        (mailbox / folder).mkdir(parents=True)
    test_settings = Settings(database_url=test_url, mailbox_root=mailbox,
                             mailbox_id=f'test-{uuid.uuid4()}', knowledge_source_id=f'test-{uuid.uuid4()}')
    migration = Config('alembic.ini')
    migration.attributes['settings'] = test_settings
    # 迁移在独立线程运行，避免 Alembic 的 asyncio.run 嵌套事件循环。
    await asyncio.to_thread(command.upgrade, migration, 'head')
    await asyncio.to_thread(command.upgrade, migration, 'head')
    database = Database(test_settings)
    try:
        await database.check_ready()
        yield database
    finally:
        await database.close()
