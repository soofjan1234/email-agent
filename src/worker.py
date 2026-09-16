"""独立 worker 负责历史初始化；不把历史邮件送入 Graph。"""
import argparse
import asyncio
import logging
import signal
import sys

from config import Settings
from db import Database
from services.mail_sync import MailSyncService


async def run_once(settings=None):
    """检查依赖并执行一次历史初始化；成功任务会跳过。"""
    database = Database(settings or Settings())
    try:
        await database.check_ready()
        await MailSyncService(database).run_history()
    finally:
        await database.close()


async def serve():
    """周期恢复未完成的历史任务，错误保存在任务中，退出时释放连接。"""
    database = Database(Settings())
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        if sys.platform != 'win32':
            loop.add_signal_handler(signum, stopped.set)
    try:
        await database.check_ready()
        service = MailSyncService(database)
        await service.ensure_initialization()
        logging.info('worker ready; historical initialization enabled')
        while not stopped.is_set():
            try:
                await service.run_history()
            except Exception:
                logging.warning('historical initialization failed; see sync job status')
            try:
                await asyncio.wait_for(stopped.wait(), timeout=database.settings.worker_poll_seconds)
            except TimeoutError:
                pass
    finally:
        await database.close()


def main():
    """根目录通过 python -m worker 启动，Windows 显式使用 Selector。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='Run historical initialization once and exit')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_once() if args.once else serve(), loop_factory=asyncio.SelectorEventLoop)


if __name__ == '__main__':
    main()
