"""验证合成扩容语料可重复生成，并只写入独立历史邮箱。"""
from email import policy
from email.parser import BytesParser
import hashlib
import uuid

import pytest

from scripts.seed_synthetic_shadow_mailbox import (SYNTHETIC_MAILBOX_ID, SyntheticMailboxError,
                                                    generate_mailbox, load_synthetic_history)
from scripts.report_synthetic_shadow_augmentation import render_markdown


def file_hashes(root):
    """返回相对路径到内容哈希，比较两次生成是否字节级稳定。"""
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*.eml'))}


def test_synthetic_mailbox_has_exact_counts_and_stable_headers(tmp_path):
    """生成 1,346/711 个文件，所有地址和关联头均保持受控。"""
    first, second = tmp_path / 'first', tmp_path / 'second'

    generate_mailbox(first)
    generate_mailbox(second)

    inbox = sorted((first / 'inbox').glob('*.eml'))
    sent = sorted((first / 'sent').glob('*.eml'))
    assert len(inbox) == 1346
    assert len(sent) == 711
    assert file_hashes(first) == file_hashes(second)

    inbox_messages = {BytesParser(policy=policy.default).parsebytes(path.read_bytes())['Message-ID']
                      for path in inbox}
    for path in sent:
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        assert message['X-Synthetic-Source'] == 'imap-shadow-augmentation-v1'
        assert message['In-Reply-To'] in inbox_messages
        assert message['References'] == message['In-Reply-To']
        assert str(message['From']).endswith('@example.invalid')
    assert all(path.name.startswith('synthetic-') for path in inbox + sent)


def test_synthetic_mailbox_refuses_nonempty_output_without_clean_option(tmp_path):
    """未知目录内容必须阻止生成，避免脚本静默覆盖本地文件。"""
    output = tmp_path / 'existing'
    output.mkdir()
    (output / 'unexpected.txt').write_text('keep me', encoding='utf-8')

    with pytest.raises(SyntheticMailboxError, match='output_not_empty'):
        generate_mailbox(output)


def test_summary_markdown_contains_counts_but_no_mail_content():
    """汇总只能保留计数与口径，不能意外输出正文或地址字段。"""
    record = {'scanned_count': 243, 'paired_count': 12, 'candidate_count': 12,
              'email_count': 0, 'outbox_count': 0}

    rendered = render_markdown({'real_imap_baseline': record, 'synthetic_increment': record})

    assert '243' in rendered and '2,300' in rendered
    assert '正文' in rendered and '@' not in rendered


async def test_synthetic_history_load_is_isolated_from_business_email_flow(database, tmp_path):
    """历史加载只生成配对和候选，不创建业务邮件或模拟发件。"""
    output = tmp_path / 'synthetic-mailbox'
    generate_mailbox(output)
    mailbox_id = f'test-synthetic-{uuid.uuid4()}'
    settings = database.settings.model_copy(update={
        'mailbox_id': mailbox_id,
        'mailbox_root': output,
        'mailbox_adapter': 'mock',
    })

    report = await load_synthetic_history(settings, output, mailbox_id=mailbox_id)

    assert report == {
        'mailbox_id': mailbox_id,
        'scanned_count': 2057,
        'paired_count': 711,
        'candidate_count': 711,
        'source_count': 2057,
        'email_count': 0,
        'outbox_count': 0,
    }
