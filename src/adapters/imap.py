"""只读 IMAP 适配器：使用 UID 游标拉取原始邮件，不修改服务器状态。"""
from dataclasses import dataclass
import hashlib
import imaplib

from adapters.mailbox import SnapshotMail


@dataclass(frozen=True)
class IMAPIncomingMail:
    """一封带文件夹永久 UID 的原始收件。"""
    uid: int
    raw_content: bytes


@dataclass(frozen=True)
class IMAPIncrementalBatch:
    """一次只读查询返回的 UID 版本和有序邮件。"""
    uidvalidity: str
    mails: tuple[IMAPIncomingMail, ...]


@dataclass(frozen=True)
class IMAPHistorySnapshot:
    """固定历史原文及捕获瞬间的收件箱高水位。"""
    mails: tuple[SnapshotMail, ...]
    uidvalidity: str
    last_uid: int


class IMAPMailboxAdapter:
    """通过 imaplib 执行只读 SELECT、UID SEARCH 与 UID FETCH。"""

    def __init__(self, host, port, use_ssl, username, password, inbox_folder, sent_folder):
        """保存运行配置；凭据只在登录调用中使用，不写日志或异常。"""
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.username = username
        self.password = password
        self.inbox_folder = inbox_folder
        self.sent_folder = sent_folder

    def _connect(self):
        """建立短连接并登录，调用者必须在 finally 中退出。"""
        connection_type = imaplib.IMAP4_SSL if self.use_ssl else imaplib.IMAP4
        client = connection_type(self.host, self.port)
        status, _ = client.login(self.username, self.password)
        if status != 'OK':
            raise RuntimeError('imap_login_failed')
        return client

    @staticmethod
    def _uidvalidity(client):
        """读取当前已选择文件夹的 UID 版本，缺失时拒绝建立游标。"""
        _, values = client.response('UIDVALIDITY')
        if not values or values[0] is None:
            raise RuntimeError('imap_uidvalidity_missing')
        return values[0].decode('ascii') if isinstance(values[0], bytes) else str(values[0])

    @staticmethod
    def _search_uids(client, start_uid=None):
        """按 UID 搜索并返回升序整数；删除造成的空洞属于合法情况。"""
        criterion = 'ALL' if start_uid is None else f'UID {start_uid}:*'
        status, values = client.uid('search', None, criterion)
        if status != 'OK':
            raise RuntimeError('imap_search_failed')
        raw = values[0] if values else b''
        return sorted(int(value) for value in raw.split())

    @staticmethod
    def _fetch_raw(client, uid):
        """以 UID 读取 RFC822 原文，不设置 Seen 标记。"""
        status, values = client.uid('fetch', str(uid), '(BODY.PEEK[])')
        if status != 'OK':
            raise RuntimeError('imap_fetch_failed')
        for value in values or ():
            if isinstance(value, tuple) and len(value) >= 2 and isinstance(value[1], bytes):
                return value[1]
        raise RuntimeError('imap_message_missing')

    def _select(self, client, folder):
        """只读选择显式文件夹，禁止隐式创建或写入邮件标志。"""
        status, _ = client.select(folder, readonly=True)
        if status != 'OK':
            raise RuntimeError('imap_folder_unavailable')

    def fetch_inbox_after(self, cursor):
        """返回收件箱中 UID 大于已提交游标的所有原文。"""
        client = self._connect()
        try:
            self._select(client, self.inbox_folder)
            uidvalidity = self._uidvalidity(client)
            mails = tuple(IMAPIncomingMail(uid, self._fetch_raw(client, uid))
                          for uid in self._search_uids(client, cursor + 1))
            return IMAPIncrementalBatch(uidvalidity, mails)
        finally:
            try:
                client.logout()
            except imaplib.IMAP4.error:
                pass

    def capture_history(self):
        """先固定收件 UID 高水位，再只读捕获收件和已发送原文。"""
        client = self._connect()
        try:
            # 1. 收件箱 UID 列表决定初始化边界，后到邮件留给 B1。
            self._select(client, self.inbox_folder)
            uidvalidity = self._uidvalidity(client)
            inbox_uids = self._search_uids(client)
            last_uid = inbox_uids[-1] if inbox_uids else 0
            mails = []
            for uid in inbox_uids:
                raw = self._fetch_raw(client, uid)
                mails.append(SnapshotMail('inbox', f'imap:{self.inbox_folder}:{uid}',
                                          hashlib.sha256(raw).hexdigest(), raw))
            # 2. 已发送文件夹只用于历史回复关联，不参与收件增量游标。
            self._select(client, self.sent_folder)
            for uid in self._search_uids(client):
                raw = self._fetch_raw(client, uid)
                mails.append(SnapshotMail('sent', f'imap:{self.sent_folder}:{uid}',
                                          hashlib.sha256(raw).hexdigest(), raw))
            return IMAPHistorySnapshot(tuple(mails), uidvalidity, last_uid)
        finally:
            try:
                client.logout()
            except imaplib.IMAP4.error:
                pass
