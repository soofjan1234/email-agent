"""生成并投影 synthetic v2；仅本地 Mock 邮箱，不读取 IMAP 或调用 SMTP。"""
import argparse
import asyncio
from email import policy
from email.parser import BytesParser
import json
from pathlib import Path
import sys

from adapters.mailbox import MockMailboxAdapter
from config import Settings
from db import Database
from services.mail_sync import MailSyncService
try:
    # 作为模块运行时使用仓库命名空间；直接执行脚本时回退到同目录模块。
    from scripts import seed_synthetic_shadow_mailbox as v1
except ModuleNotFoundError:
    import seed_synthetic_shadow_mailbox as v1


SYNTHETIC_MAILBOX_ID = 'imap-shadow-20260918-synthetic-v2'
SYNTHETIC_SOURCE = 'imap-shadow-augmentation-v2'
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / 'data/synthetic-shadow-mailbox-20260918-v2'
SPAM_MARKERS = ('unsubscribe', 'limited offer', 'buy now')
# 从 v1 的 413/222 未回复配额中各抽走 83/44，余下 330/178 仍保持约 65/35。
SPAM_BY_SCOPE = {'core': 83, 'research-derived': 44}


class SyntheticV2Error(ValueError):
    """v2 目录、来源标识或统计口径不符合隔离边界时终止。"""


def _replace_source_and_spam(path, spam):
    """把 v1 字节模板仅在新目录中转换为 v2 头，并按配额植入垃圾标记。"""
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    message.replace_header('X-Synthetic-Source', SYNTHETIC_SOURCE)
    if spam:
        message.replace_header('Subject', 'Limited offer - buy now')
        message.set_content('Limited offer: buy now and unsubscribe. 此邮件仅用于隔离垃圾分流测试。')
    path.write_bytes(message.as_bytes(policy=policy.SMTP))


def _is_unmatched_inbox(path):
    """v1 固定约定 1–711 为已配对收件，712 起才是无回复 Inbox。"""
    return int(Path(path).stem.rsplit('-', 1)[-1]) >= 712


def generate_mailbox(output):
    """复用 v1 配对语料，在独立目录构造 127 垃圾和 508 售后未回复邮件。"""
    output = Path(output).resolve()
    v1.generate_mailbox(output)
    remaining = dict(SPAM_BY_SCOPE)
    for folder in ('inbox', 'sent'):
        for path in sorted((output / folder).glob('*.eml')):
            message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
            spam = False
            if folder == 'inbox' and _is_unmatched_inbox(path):
                scope = message['X-Synthetic-Scope']
                bucket = 'core' if scope.startswith('core-') else scope
                if remaining.get(bucket, 0) > 0:
                    remaining[bucket] -= 1
                    spam = True
            _replace_source_and_spam(path, spam)
    if remaining != {'core': 0, 'research-derived': 0}:
        raise SyntheticV2Error('spam_quota_not_consumed')
    return validate_mailbox(output)


def validate_mailbox(output):
    """验证精确文件数、v2 来源头、711 配对及 127/508 未回复分流比例。"""
    output = Path(output).resolve()
    inbox = sorted((output / 'inbox').glob('synthetic-*.eml'))
    sent = sorted((output / 'sent').glob('synthetic-*.eml'))
    if len(inbox) != 1346 or len(sent) != 711:
        raise SyntheticV2Error('generated_file_count_invalid')
    inbox_ids, spam_count, business_count = set(), 0, 0
    for path in inbox:
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        if message['X-Synthetic-Source'] != SYNTHETIC_SOURCE or not message['Message-ID']:
            raise SyntheticV2Error('synthetic_header_invalid')
        inbox_ids.add(message['Message-ID'])
        if _is_unmatched_inbox(path):
            text = (message['Subject'] or '') + '\n' + message.get_content()
            if any(marker in text.lower() for marker in SPAM_MARKERS):
                spam_count += 1
            else:
                business_count += 1
    for path in sent:
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        if (message['X-Synthetic-Source'] != SYNTHETIC_SOURCE or message['In-Reply-To'] not in inbox_ids
                or message['References'] != message['In-Reply-To']):
            raise SyntheticV2Error('synthetic_pairing_invalid')
    if (spam_count, business_count) != (127, 508):
        raise SyntheticV2Error('unmatched_split_invalid')
    return {'inbox_count': len(inbox), 'sent_count': len(sent), 'spam_count': spam_count,
            'business_count': business_count}


async def load_and_project(settings, output, *, mailbox_id=SYNTHETIC_MAILBOX_ID):
    """加载 v2 历史后只投影 635 封 unmatched Inbox，绝不启动工作流。"""
    output = Path(output).resolve()
    if (settings.mailbox_id != mailbox_id or settings.mailbox_adapter != 'mock'
            or Path(settings.mailbox_root).resolve() != output):
        raise SyntheticV2Error('synthetic_settings_invalid')
    validate_mailbox(output)
    database = Database(settings)
    try:
        await database.check_ready()
        if await v1._collect_history_counts(database, mailbox_id) is not None:
            raise SyntheticV2Error('synthetic_mailbox_already_initialized')
        service = MailSyncService(database, MockMailboxAdapter(output))
        if not await service.run_history():
            raise SyntheticV2Error('synthetic_history_not_processed')
        projected = await service.project_unmatched_history()
        report = await v1._collect_history_counts(database, mailbox_id)
        if projected != 635 or report['email_count'] != 635 or report['outbox_count'] != 0:
            raise SyntheticV2Error('synthetic_projection_counts_invalid')
        return {key: report[key] for key in ('mailbox_id', 'scanned_count', 'paired_count', 'candidate_count',
            'source_count', 'email_count', 'outbox_count')} | {'spam_count': 127, 'business_count': 508}
    finally:
        await database.close()


def run_async(coroutine):
    """在 Windows 为 Psycopg 选择兼容事件循环。"""
    if sys.platform != 'win32':
        return asyncio.run(coroutine)
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


def main():
    """生成 v2；指定加载参数时才写入当前配置的隔离数据库。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--load-and-project', action='store_true')
    args = parser.parse_args()
    report = generate_mailbox(args.output)
    if args.load_and_project:
        base = Settings()
        settings = base.model_copy(update={'mailbox_id': SYNTHETIC_MAILBOX_ID, 'mailbox_root': Path(args.output),
            'mailbox_adapter': 'mock'})
        report |= run_async(load_and_project(settings, args.output))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
