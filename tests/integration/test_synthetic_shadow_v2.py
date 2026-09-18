"""验证 synthetic v2 与历史 v1 使用不同目录和可审计垃圾分流配额。"""
from email import policy
from email.parser import BytesParser

from scripts.seed_synthetic_shadow_mailbox_v2 import (SPAM_MARKERS, SYNTHETIC_SOURCE, _is_unmatched_inbox,
                                                       generate_mailbox)


def test_v2_has_isolated_source_and_exact_unmatched_split(tmp_path):
    """v2 保留 1,346/711 规模，并把无回复邮件严格拆为 127/508。"""
    output = tmp_path / 'synthetic-v2'
    summary = generate_mailbox(output)
    assert summary == {'inbox_count': 1346, 'sent_count': 711, 'spam_count': 127, 'business_count': 508}
    spam = 0
    for path in (output / 'inbox').glob('*.eml'):
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        assert message['X-Synthetic-Source'] == SYNTHETIC_SOURCE
        if _is_unmatched_inbox(path):
            text = ((message['Subject'] or '') + '\n' + message.get_content()).lower()
            spam += int(any(marker in text for marker in SPAM_MARKERS))
    assert spam == 127
