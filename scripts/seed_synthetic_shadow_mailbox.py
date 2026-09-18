"""生成并加载可审计的 LincStation 合成历史邮箱，不连接 IMAP 或 SMTP。"""
import argparse
import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime
import json
from pathlib import Path
import shutil
import sys

from sqlalchemy import func, select

from adapters.mailbox import MockMailboxAdapter
from config import Settings
from db import Database
from models import CaseCandidate, Email, HistoricalEmailPair, MailSource, MailSyncJob, SimulatedOutbox
from services.mail_sync import MailSyncService


# 固定邮箱标识，确保合成历史记录不会和真实 IMAP 来源混用。
SYNTHETIC_MAILBOX_ID = 'imap-shadow-20260918-synthetic-v1'
SYNTHETIC_SOURCE = 'imap-shadow-augmentation-v1'
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_PATH = REPOSITORY_ROOT / 'docs/changes/2026-09-18-real-imap-shadow-test/research.md'
DEFAULT_OUTPUT = REPOSITORY_ROOT / 'data/synthetic-shadow-mailbox-20260918'
BASE_TIME = datetime(2026, 9, 1, tzinfo=timezone.utc)


class SyntheticMailboxError(ValueError):
    """表示合成邮箱的前置条件、目录或隔离边界不符合要求。"""


@dataclass(frozen=True)
class TopicQuota:
    """定义一个可追溯主题及其确定的收件数量。"""

    key: str
    count: int
    scope: str
    subject: str
    question: str
    answer: str


# 已回复的 711 个案例：462 个核心 NAS 主题和 249 个调研衍生主题。
PAIRED_QUOTAS = (
    TopicQuota('system-download', 47, 'core-system', 'LincOS 下载入口咨询',
               '我需要确认当前设备适用的 LincOS 下载入口和版本信息。',
               '请先确认设备型号和当前系统版本，再从官方支持页选择对应下载入口。'),
    TopicQuota('system-upgrade', 46, 'core-system', 'LincOS 升级后服务检查',
               '系统升级完成后，我想确认基础服务是否已经正常启动。',
               '请记录升级后的版本和服务状态；如服务未启动，请不要重复升级，先收集状态信息。'),
    TopicQuota('system-service', 46, 'core-system', 'LincOS 服务管理咨询',
               '管理页面中一个服务没有显示为正常运行，我该先检查什么？',
               '请先核对服务状态和系统版本，并保留错误提示后再进行变更。'),
    TopicQuota('system-docker', 46, 'core-system', 'Docker 功能使用咨询',
               '我需要确认设备上的 Docker 功能或容器服务入口。',
               '请先确认当前版本支持的 Docker 功能，并检查服务状态，不要直接删除现有容器数据。'),
    TopicQuota('device-boot-screen', 40, 'core-device', '设备停留在启动界面',
               '设备启动后停留在品牌启动界面，管理页面尚不可访问。',
               '请先按支持页的重置和恢复步骤排查，并在重刷前确认可用备份。'),
    TopicQuota('device-network', 40, 'core-device', '本地网络无法连接设备',
               '本地网络中无法打开设备管理界面，需要确认连接路径。',
               '请先确认设备获取到的地址、客户端网络和访问协议，再进行网络配置调整。'),
    TopicQuota('device-rebuild', 40, 'core-device', '系统重建前的确认',
               '我需要执行系统重建，想确认恢复介质和注意事项。',
               '重建前请确认型号、恢复介质和已有数据备份；不要在来源不明的镜像上继续操作。'),
    TopicQuota('device-migration', 40, 'core-device', '数据迁移步骤咨询',
               '我计划迁移数据到新存储布局，需要先核对哪些事项？',
               '请先确认源盘、目标盘、可用容量和已验证备份，再按官方迁移路径操作。'),
    TopicQuota('hardware-drive', 39, 'core-hardware', '硬盘或 NVMe 稳定性咨询',
               '部分硬盘或 NVMe 的状态不稳定，需要基础排查建议。',
               '请先记录盘位、状态和复现条件；关机后再检查物理连接，避免带电重新插拔。'),
    TopicQuota('hardware-fan', 39, 'core-hardware', '风扇噪音咨询',
               '设备运行时风扇噪音较大，想确认安全的检查路径。',
               '请先记录温度和风扇设置；如支持页提供风扇曲线说明，请按对应型号的步骤调整。'),
    TopicQuota('hardware-stylus', 39, 'core-hardware', '触控笔或触控配件咨询',
               '触控屏或触控笔配件响应异常，需要确认基础检查步骤。',
               '请确认型号和系统状态；如触控屏无响应，优先使用支持页列出的重置路径。'),
    TopicQuota('remote-access', 63, 'research-derived', '远程访问或本地云登录问题',
               '我在远程访问或本地云登录时无法打开设备。',
               '请先区分地址解析、网络可达性和登录状态，并提供不含凭据的错误现象。'),
    TopicQuota('client-compatibility', 62, 'research-derived', '客户端平台兼容性咨询',
               '我想确认当前桌面或移动端是否有可用客户端。',
               '请使用官方支持页列出的客户端或 Web UI 路径，并以当前页面说明为准。'),
    TopicQuota('unraid-setup', 62, 'research-derived', 'Unraid 初始配置与应用教程',
               '初始配置完成后，我需要寻找存储、共享或应用安装教程。',
               '请按与设备型号匹配的官方教程完成基础配置，再继续部署应用。'),
    TopicQuota('drive-seating', 62, 'research-derived', '磁盘就位与状态指示咨询',
               '设备只识别到部分磁盘，我需要确认基础检查顺序。',
               '请关机后检查磁盘是否完全就位，并结合状态指示和支持页继续排查。'),
)


# 无回复的 635 个收件沿用同一主题比例，但没有对应 Sent 文件。
UNPAIRED_QUOTAS = (
    TopicQuota('system-download', 42, 'core-system', 'LincOS 下载入口咨询',
               '我需要确认当前设备适用的 LincOS 下载入口和版本信息。', ''),
    TopicQuota('system-upgrade', 41, 'core-system', 'LincOS 升级后服务检查',
               '系统升级完成后，我想确认基础服务是否已经正常启动。', ''),
    TopicQuota('system-service', 41, 'core-system', 'LincOS 服务管理咨询',
               '管理页面中一个服务没有显示为正常运行，我该先检查什么？', ''),
    TopicQuota('system-docker', 41, 'core-system', 'Docker 功能使用咨询',
               '我需要确认设备上的 Docker 功能或容器服务入口。', ''),
    TopicQuota('device-boot-screen', 36, 'core-device', '设备停留在启动界面',
               '设备启动后停留在品牌启动界面，管理页面尚不可访问。', ''),
    TopicQuota('device-network', 36, 'core-device', '本地网络无法连接设备',
               '本地网络中无法打开设备管理界面，需要确认连接路径。', ''),
    TopicQuota('device-rebuild', 36, 'core-device', '系统重建前的确认',
               '我需要执行系统重建，想确认恢复介质和注意事项。', ''),
    TopicQuota('device-migration', 35, 'core-device', '数据迁移步骤咨询',
               '我计划迁移数据到新存储布局，需要先核对哪些事项？', ''),
    TopicQuota('hardware-drive', 35, 'core-hardware', '硬盘或 NVMe 稳定性咨询',
               '部分硬盘或 NVMe 的状态不稳定，需要基础排查建议。', ''),
    TopicQuota('hardware-fan', 35, 'core-hardware', '风扇噪音咨询',
               '设备运行时风扇噪音较大，想确认安全的检查路径。', ''),
    TopicQuota('hardware-stylus', 35, 'core-hardware', '触控笔或触控配件咨询',
               '触控屏或触控笔配件响应异常，需要确认基础检查步骤。', ''),
    TopicQuota('remote-access', 56, 'research-derived', '远程访问或本地云登录问题',
               '我在远程访问或本地云登录时无法打开设备。', ''),
    TopicQuota('client-compatibility', 56, 'research-derived', '客户端平台兼容性咨询',
               '我想确认当前桌面或移动端是否有可用客户端。', ''),
    TopicQuota('unraid-setup', 55, 'research-derived', 'Unraid 初始配置与应用教程',
               '初始配置完成后，我需要寻找存储、共享或应用安装教程。', ''),
    TopicQuota('drive-seating', 55, 'research-derived', '磁盘就位与状态指示咨询',
               '设备只识别到部分磁盘，我需要确认基础检查顺序。', ''),
)


def _expanded_topics(quotas: Iterable[TopicQuota]):
    """按配额展开主题，保证生成顺序和每个主题的计数稳定。"""
    for quota in quotas:
        yield from (quota for _ in range(quota.count))


def _check_quota_invariants():
    """启动时验证计划中的 65/35 配额，防止维护时静默改变规模。"""
    paired = tuple(_expanded_topics(PAIRED_QUOTAS))
    unpaired = tuple(_expanded_topics(UNPAIRED_QUOTAS))
    if len(paired) != 711 or len(unpaired) != 635:
        raise RuntimeError('synthetic_quota_total_invalid')
    if sum(topic.scope.startswith('core-') for topic in paired) != 462:
        raise RuntimeError('paired_core_quota_invalid')
    if sum(topic.scope.startswith('core-') for topic in unpaired) != 413:
        raise RuntimeError('unpaired_core_quota_invalid')


def _require_research_catalog():
    """确认阶段 1 主题目录存在，禁止跳过来源记录直接生成语料。"""
    if not RESEARCH_PATH.is_file():
        raise SyntheticMailboxError('research_catalog_missing')
    content = RESEARCH_PATH.read_text(encoding='utf-8')
    required_markers = ('核心 NAS 支持主题', '`research-derived`', '可生成的匿名问题场景')
    if not all(marker in content for marker in required_markers):
        raise SyntheticMailboxError('research_catalog_incomplete')


def _message_id(serial: int):
    """为每个收件生成稳定且符合配对器要求的 Message-ID。"""
    return f'<synthetic-{serial:04d}@example.invalid>'


def _make_message(*, serial: int, topic: TopicQuota, sender: str, recipient: str,
                  body: str, is_reply: bool):
    """构造确定的 UTF-8 纯文本邮件，并写入合成来源与主题审计头。"""
    message = EmailMessage(policy=policy.SMTP)
    message['From'] = sender
    message['To'] = recipient
    message['Subject'] = topic.subject
    message['Date'] = format_datetime(BASE_TIME + timedelta(minutes=serial, hours=int(is_reply)))
    message['Message-ID'] = _message_id(serial) if not is_reply else f'<synthetic-reply-{serial:04d}@example.invalid>'
    message['X-Synthetic-Source'] = SYNTHETIC_SOURCE
    message['X-Synthetic-Topic'] = topic.key
    message['X-Synthetic-Scope'] = topic.scope
    if is_reply:
        message['In-Reply-To'] = _message_id(serial)
        message['References'] = _message_id(serial)
    message.set_content(body)
    return message.as_bytes()


def _prepare_output(output: Path):
    """只接受空目录作为生成目标，防止默认执行覆盖已有语料。"""
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SyntheticMailboxError('output_not_empty')
    for folder in ('inbox', 'sent'):
        (output / folder).mkdir(parents=True, exist_ok=True)
    return output


def generate_mailbox(output: Path):
    """生成精确数量的收件与已回复邮件，不触发数据库、IMAP 或网络访问。"""
    _check_quota_invariants()
    _require_research_catalog()
    output = _prepare_output(Path(output))
    paired_topics = tuple(_expanded_topics(PAIRED_QUOTAS))
    unpaired_topics = tuple(_expanded_topics(UNPAIRED_QUOTAS))

    # 1. 每个已回复案例先写 Inbox，再写引用同一 Message-ID 的 Sent。
    for serial, topic in enumerate(paired_topics, start=1):
        question = f'合成咨询 #{serial:04d}\n\n{topic.question}\n\n此邮件仅用于隔离测试。'
        answer = f'合成支持回复 #{serial:04d}\n\n{topic.answer}\n\n此回复仅用于隔离测试。'
        (output / 'inbox' / f'synthetic-inbox-{serial:04d}.eml').write_bytes(_make_message(
            serial=serial, topic=topic, sender=f'<customer-{serial:04d}@example.invalid>',
            recipient='<support@example.invalid>', body=question, is_reply=False))
        (output / 'sent' / f'synthetic-sent-{serial:04d}.eml').write_bytes(_make_message(
            serial=serial, topic=topic, sender='<support@example.invalid>',
            recipient=f'<customer-{serial:04d}@example.invalid>', body=answer, is_reply=True))

    # 2. 未回复收件从 712 起编号，保证文件名和 Message-ID 不与已回复案例冲突。
    for offset, topic in enumerate(unpaired_topics, start=712):
        question = f'合成咨询 #{offset:04d}\n\n{topic.question}\n\n此邮件仅用于隔离测试。'
        (output / 'inbox' / f'synthetic-inbox-{offset:04d}.eml').write_bytes(_make_message(
            serial=offset, topic=topic, sender=f'<customer-{offset:04d}@example.invalid>',
            recipient='<support@example.invalid>', body=question, is_reply=False))
    return {'inbox_count': len(paired_topics) + len(unpaired_topics), 'sent_count': len(paired_topics)}


def _validate_generated_mailbox(output: Path):
    """在加载前检查文件数、来源头、地址域和收发关联，拒绝被篡改的语料。"""
    output = Path(output).resolve()
    inbox = sorted((output / 'inbox').glob('synthetic-*.eml'))
    sent = sorted((output / 'sent').glob('synthetic-*.eml'))
    if len(inbox) != 1346 or len(sent) != 711:
        raise SyntheticMailboxError('generated_file_count_invalid')
    inbox_ids = set()
    for path in inbox:
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        if message['X-Synthetic-Source'] != SYNTHETIC_SOURCE or not message['Message-ID']:
            raise SyntheticMailboxError('synthetic_header_invalid')
        if not all(str(address).endswith('@example.invalid') for address in (message['From'], message['To'])):
            raise SyntheticMailboxError('synthetic_address_invalid')
        inbox_ids.add(message['Message-ID'])
    for path in sent:
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        if (message['X-Synthetic-Source'] != SYNTHETIC_SOURCE
                or message['In-Reply-To'] not in inbox_ids
                or message['References'] != message['In-Reply-To']):
            raise SyntheticMailboxError('synthetic_pairing_invalid')


async def _collect_history_counts(database: Database, mailbox_id: str):
    """只读取指定邮箱的任务、来源、配对、候选和业务流计数。"""
    async with database.session() as session:
        job = await session.scalar(select(MailSyncJob).where(
            MailSyncJob.mailbox_id == mailbox_id, MailSyncJob.mode == 'historical_backfill'))
        if job is None:
            return None
        source_count = await session.scalar(select(func.count()).select_from(MailSource).where(
            MailSource.sync_job_id == job.id))
        pair_count = await session.scalar(select(func.count()).select_from(HistoricalEmailPair).where(
            HistoricalEmailPair.sync_job_id == job.id))
        candidate_count = await session.scalar(select(func.count()).select_from(CaseCandidate).join(
            HistoricalEmailPair).where(HistoricalEmailPair.sync_job_id == job.id))
        prefix = mailbox_id + ':'
        email_count = await session.scalar(select(func.count()).select_from(Email).where(
            Email.client_request_id.startswith(prefix)))
        outbox_count = await session.scalar(select(func.count()).select_from(SimulatedOutbox).join(Email).where(
            Email.client_request_id.startswith(prefix)))
        return {
            'mailbox_id': mailbox_id,
            'status': job.status,
            'scanned_count': job.scanned_count,
            'paired_count': job.paired_count,
            'candidate_count': job.candidate_count,
            'source_count': source_count,
            'pair_row_count': pair_count,
            'candidate_row_count': candidate_count,
            'email_count': email_count,
            'outbox_count': outbox_count,
            'unsupported_reasons': job.unsupported_reasons,
        }


async def load_synthetic_history(settings: Settings, output: Path, *, mailbox_id=SYNTHETIC_MAILBOX_ID):
    """通过 MockMailboxAdapter 加载合成历史，不投影 Email 或触发工作流。"""
    output = Path(output).resolve()
    if (settings.mailbox_id != mailbox_id or settings.mailbox_adapter != 'mock'
            or (mailbox_id != SYNTHETIC_MAILBOX_ID and not mailbox_id.startswith('test-synthetic-'))):
        raise SyntheticMailboxError('synthetic_settings_invalid')
    if Path(settings.mailbox_root).resolve() != output:
        raise SyntheticMailboxError('synthetic_root_mismatch')
    _validate_generated_mailbox(output)
    database = Database(settings)
    try:
        await database.check_ready()
        # 1. 预先拒绝已存在任务，避免把新的文件追加到既有 synthetic 邮箱历史。
        if await _collect_history_counts(database, mailbox_id) is not None:
            raise SyntheticMailboxError('synthetic_mailbox_already_initialized')
        # 2. 仅注入本地 Mock 适配器，服务不会构造 IMAP、SMTP 或工作流对象。
        service = MailSyncService(database, MockMailboxAdapter(output))
        if not await service.run_history():
            raise SyntheticMailboxError('synthetic_history_not_processed')
        result = await _collect_history_counts(database, mailbox_id)
        if result is None or result['status'] != 'succeeded':
            raise SyntheticMailboxError('synthetic_history_not_succeeded')
        report = {key: result[key] for key in ('mailbox_id', 'scanned_count', 'paired_count',
                                                'candidate_count', 'source_count', 'email_count', 'outbox_count')}
        if report != {
            'mailbox_id': mailbox_id,
            'scanned_count': 2057,
            'paired_count': 711,
            'candidate_count': 711,
            'source_count': 2057,
            'email_count': 0,
            'outbox_count': 0,
        }:
            raise SyntheticMailboxError('synthetic_history_counts_invalid')
        return report
    finally:
        await database.close()


async def collect_history_report(settings: Settings, mailbox_id: str):
    """为报告脚本提供只读历史统计，不修改真实或合成数据。"""
    database = Database(settings)
    try:
        await database.check_ready()
        return await _collect_history_counts(database, mailbox_id)
    finally:
        await database.close()


def _clean_default_output(output: Path):
    """只允许显式清理计划规定的默认目录，避免参数误指向其他路径。"""
    if Path(output).resolve() != DEFAULT_OUTPUT.resolve():
        raise SyntheticMailboxError('clean_target_rejected')
    if output.exists():
        shutil.rmtree(output)


def _parse_arguments():
    """解析生成、加载和显式清理选项；默认操作只生成本地语料。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--load-only', action='store_true')
    parser.add_argument('--clean', action='store_true')
    return parser.parse_args()


def run_async(coroutine):
    """在 Windows 为 Psycopg 选择兼容事件循环，其余平台沿用默认实现。"""
    if sys.platform != 'win32':
        return asyncio.run(coroutine)
    # Psycopg 异步连接不支持 Windows 默认 ProactorEventLoop。
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


async def _main_async(args):
    """执行命令行请求，并把脱敏计数以 JSON 输出给验证记录。"""
    output = args.output.resolve()
    if args.clean:
        _clean_default_output(output)
    if args.load_only:
        settings = Settings(mailbox_id=SYNTHETIC_MAILBOX_ID, mailbox_root=output, mailbox_adapter='mock')
        return await load_synthetic_history(settings, output)
    return generate_mailbox(output)


def main():
    """提供脚本入口；业务异常保留错误码且不输出路径之外的敏感配置。"""
    args = _parse_arguments()
    print(json.dumps(run_async(_main_async(args)), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
