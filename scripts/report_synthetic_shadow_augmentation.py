"""输出真实 IMAP 基线与合成扩容数据的脱敏只读汇总。"""
import argparse
import asyncio
import json

from config import Settings
try:
    # 作为测试模块导入时，仓库根目录在 sys.path 中。
    from scripts.seed_synthetic_shadow_mailbox import (SYNTHETIC_MAILBOX_ID, collect_history_report, run_async)
except ModuleNotFoundError:
    # 直接执行脚本时，Python 只将 scripts/ 自身加入 sys.path。
    from seed_synthetic_shadow_mailbox import SYNTHETIC_MAILBOX_ID, collect_history_report, run_async


def _parse_arguments():
    """只允许选择 JSON 或 Markdown 输出，不接受会改变数据库的参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--format', choices=('json', 'markdown'), default='json')
    return parser.parse_args()


async def build_report(settings: Settings):
    """读取两个 mailbox 的聚合计数，并明确真实与合成数据的解释边界。"""
    if settings.mailbox_id == SYNTHETIC_MAILBOX_ID:
        raise ValueError('real_mailbox_id_required_for_report')
    # 1. 分别读取真实 IMAP 基线与固定 synthetic mailbox，绝不合并源计数。
    real, synthetic = await asyncio.gather(
        collect_history_report(settings, settings.mailbox_id),
        collect_history_report(settings, SYNTHETIC_MAILBOX_ID),
    )
    # 2. 只有压测口径显示 2,300；真实问题结论始终锚定真实基线。
    return {
        'real_imap_baseline': real,
        'synthetic_increment': synthetic,
        'stress_summary': {'inbox': 1500, 'sent': 800, 'total': 2300},
        'interpretation_boundary': (
            '2,300 only describes the synthetic stress-summary scale. '
            'After-sales conclusions must use real_imap_baseline only.'),
    }


def render_markdown(report):
    """将计数渲染成不含邮件正文、地址或凭据的 Markdown 表格。"""
    rows = [
        '| 来源 | 源邮件 | 配对 | 候选 | 业务邮件 | 模拟发件 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |',
    ]
    for label, record in (('真实 IMAP 基线', report['real_imap_baseline']),
                          ('合成增量', report['synthetic_increment'])):
        if record is None:
            rows.append(f'| {label} | 未运行 | 未运行 | 未运行 | 未运行 | 未运行 |')
            continue
        rows.append('| {label} | {scanned_count} | {paired_count} | {candidate_count} | '
                    '{email_count} | {outbox_count} |'.format(label=label, **record))
    rows.extend((
        '',
        '压测汇总口径：Inbox 1,500、Sent 800、合计 2,300。',
        '',
        '边界：真实售后问题结论仅可使用真实 IMAP 基线；本报告不输出邮件正文、地址、凭据或客户身份信息。',
    ))
    return '\n'.join(rows)


async def _main_async(args):
    """读取当前隔离数据库配置并生成所选格式的只读报告。"""
    report = await build_report(Settings())
    return render_markdown(report) if args.format == 'markdown' else json.dumps(
        report, ensure_ascii=False, sort_keys=True)


def main():
    """提供命令行入口，输出不包含数据库连接信息。"""
    print(run_async(_main_async(_parse_arguments())))


if __name__ == '__main__':
    main()
