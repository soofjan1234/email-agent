"""迁移使用与应用相同的环境配置，连接串不写入日志。"""
import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from config import Settings
from models import Base


def run_migrations(connection):
    """单独迁移命令在事务中更新版本，不由 API/worker 自动调用。"""
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online():
    """测试可注入独立 Settings，其余调用读取环境。"""
    settings = context.config.attributes.get('settings') or Settings()
    engine = create_async_engine(settings.database_url.get_secret_value(), poolclass=pool.NullPool,
                                 hide_parameters=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError('A1 migrations require an online PostgreSQL database')
asyncio.run(run_online(), loop_factory=asyncio.SelectorEventLoop)
