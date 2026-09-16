"""模拟邮箱协议解析和边界内原文保存。"""
from email.message import EmailMessage

from adapters.mailbox import MockMailboxAdapter, parse_message


def test_mime_plain_body_excludes_attachments():
    """解析 MIME 正文时不把附件或 HTML 代码当作回复。"""
    mail = EmailMessage()
    mail['Message-ID'] = '<sample@example.test>'
    mail['Subject'] = 'SMB connection'
    mail.set_content('Use SMB settings.')
    mail.add_alternative('<p>HTML version</p>', subtype='html')
    mail.add_attachment(b'attachment secret', maintype='application', subtype='octet-stream', filename='log.txt')
    parsed = parse_message(mail.as_bytes())
    assert parsed['body_text'].strip() == 'Use SMB settings.'
    assert parsed['parse_error'] is None


def test_invalid_protocol_headers_are_preserved_as_unusable():
    """不通过猜测补齐无效 Message-ID，也不将 NUL 写入数据库字符串。"""
    parsed = parse_message(b'Message-ID: <bad\x00id>\nReferences: garbage\n\nbody\x00text')
    assert parsed['message_id'] is None and parsed['parse_error'] == 'invalid_headers'
    assert '\x00' not in parsed['body_text']


def test_snapshot_contains_original_bytes_and_stable_file_order(tmp_path):
    """相同输入产生相同哈希，文件变化不修改已经捕获的内容。"""
    for folder in ('inbox', 'sent'):
        (tmp_path / folder).mkdir()
    path = tmp_path / 'inbox/a.eml'
    path.write_bytes(b'Message-ID: <a>\n\noriginal')
    first = MockMailboxAdapter(tmp_path).capture()
    assert first == MockMailboxAdapter(tmp_path).capture()
    path.write_bytes(b'changed')
    assert first[0].raw_content.endswith(b'original')
