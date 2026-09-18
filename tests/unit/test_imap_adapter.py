"""真实 IMAP 适配器只读读取 UID 范围，不连接外部邮箱。"""
from email.message import EmailMessage

from adapters.imap import IMAPMailboxAdapter


def raw_mail(message_id):
    """构造最小 RFC 邮件，避免测试夹具携带真实地址。"""
    message = EmailMessage()
    message['Message-ID'] = message_id
    message['From'] = 'customer@example.test'
    message['To'] = 'support@example.test'
    message['Subject'] = 'Need help'
    message.set_content('Please help with NAS.')
    return message.as_bytes()


class FakeIMAP:
    """模拟 imaplib 的必要只读行为，并记录是否发生写操作。"""

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.selected = []
        self.commands = []
        self.messages = {11: raw_mail('<11@example.test>'), 12: raw_mail('<12@example.test>')}

    def login(self, username, password):
        self.commands.append(('login', username, password))
        return 'OK', [b'logged in']

    def select(self, folder, readonly=False):
        self.selected.append((folder, readonly))
        return 'OK', [b'2']

    def response(self, name):
        assert name == 'UIDVALIDITY'
        return 'UIDVALIDITY', [b'77']

    def uid(self, command, *arguments):
        self.commands.append((command.lower(), *arguments))
        if command.lower() == 'search':
            return 'OK', [b'11 12']
        if command.lower() == 'fetch':
            uid = int(arguments[0])
            return 'OK', [(b'RFC822', self.messages[uid])]
        raise AssertionError(command)

    def logout(self):
        self.commands.append(('logout',))
        return 'BYE', [b'logged out']


def test_fetch_after_uid_uses_readonly_folder_and_returns_stable_cursor(monkeypatch):
    """增量只读取大于已提交 UID 的邮件，UIDVALIDITY 随批次返回。"""
    fake = FakeIMAP('unused', 993)
    monkeypatch.setattr('adapters.imap.imaplib.IMAP4_SSL', lambda host, port: fake)
    adapter = IMAPMailboxAdapter('imap.example.test', 993, True, 'support@example.test',
                                 'secret-not-real', 'INBOX', 'Sent')

    batch = adapter.fetch_inbox_after(10)

    assert batch.uidvalidity == '77'
    assert [mail.uid for mail in batch.mails] == [11, 12]
    assert fake.selected == [('INBOX', True)]
    assert ('search', None, 'UID 11:*') in fake.commands
    assert ('fetch', '11', '(BODY.PEEK[])') in fake.commands
    assert not any(command[0] in ('store', 'expunge', 'append') for command in fake.commands)


def test_history_capture_freezes_inbox_uid_boundary_and_reads_sent_readonly(monkeypatch):
    """历史快照先固定收件高水位，并只读获取明确已发送文件夹。"""
    fake = FakeIMAP('unused', 993)
    monkeypatch.setattr('adapters.imap.imaplib.IMAP4_SSL', lambda host, port: fake)
    adapter = IMAPMailboxAdapter('imap.example.test', 993, True, 'support@example.test',
                                 'secret-not-real', 'INBOX', 'Sent')
    snapshot = adapter.capture_history()
    assert snapshot.uidvalidity == '77' and snapshot.last_uid == 12
    assert fake.selected == [('INBOX', True), ('Sent', True)]
    assert {mail.folder for mail in snapshot.mails} == {'inbox', 'sent'}
    assert not any(command[0] in ('store', 'expunge', 'append') for command in fake.commands)
