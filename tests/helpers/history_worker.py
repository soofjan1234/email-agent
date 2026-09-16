"""集成测试专用子进程，故障注入不进入生产启动参数。"""
import argparse
import asyncio
import json
import os
import time

from adapters.mailbox import MockMailboxAdapter
from config import Settings
from db import Database
from repositories.mail import MailRepository
from services.mail_sync import MailSyncService


async def run(args):
    """运行单次同步，并在指定事务窗口硬退出。"""
    settings = Settings()
    database = Database(settings)
    calls = 0
    original = MailRepository.save_page

    async def save_then_crash(session, job, sources):
        """在邮件已发送给 PostgreSQL、游标尚未更新时终止整个进程。"""
        nonlocal calls
        result = await original(session, job, sources)
        calls += 1
        if calls == args.crash_after_page:
            os._exit(23)
        return result

    class SlowMailbox(MockMailboxAdapter):
        """延迟快照，使两个真正独立进程的运行时间重叠。"""

        def capture(self):
            """只延迟测试适配器，不改变生产锁逻辑。"""
            time.sleep(args.snapshot_delay)
            return super().capture()

    if args.crash_after_page:
        MailRepository.save_page = staticmethod(save_then_crash)
    try:
        result = await MailSyncService(database, SlowMailbox(settings.mailbox_root), page_size=1).run_history()
        print(json.dumps({'processed': result}))
    finally:
        await database.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--crash-after-page', type=int, default=0)
    parser.add_argument('--snapshot-delay', type=float, default=0)
    asyncio.run(run(parser.parse_args()), loop_factory=asyncio.SelectorEventLoop)
