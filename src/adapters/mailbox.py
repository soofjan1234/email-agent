"""只读模拟邮箱：固定文件集合并保存原始字节，不以文件时间充当同步游标。"""
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
import hashlib
from pathlib import Path
import re


# 协议头标识保持原样，不通过主题相似度补全关系。
MESSAGE_ID = re.compile(r'<[^<>\s\x00-\x1f\x7f]+>')


@dataclass(frozen=True)
class SnapshotMail:
    """任务边界内的一个不可变文件版本。"""
    folder: str
    source_ref: str
    content_hash: str
    raw_content: bytes


class MockMailboxAdapter:
    """读取 inbox/sent 的 .eml 文件，拒绝越过配置根目录的链接。"""

    def __init__(self, root: Path):
        """只保存配置，不在错误目录下自动初始化一个空邮箱。"""
        self.root = Path(root).resolve()

    def capture(self):
        """先固定两个目录的文件集合，再读取内容，全部成功才交付快照。"""
        paths = []
        for folder in ('inbox', 'sent'):
            directory = self.root / folder
            if not directory.is_dir() or not directory.resolve().is_relative_to(self.root):
                raise ValueError('mailbox_unavailable')
            paths.extend((folder, path) for path in sorted(directory.glob('*.eml')))
        snapshot = []
        for folder, path in paths:
            if not path.resolve().is_relative_to(self.root) or not path.is_file():
                raise ValueError('mailbox_path_rejected')
            raw = path.read_bytes()
            snapshot.append(SnapshotMail(folder, f'{folder}/{path.name}',
                                          hashlib.sha256(raw).hexdigest(), raw))
        return snapshot


def parse_message(raw: bytes):
    """解析纯文本 MIME 正文，异常或不支持格式保留原文并禁止自动配对。"""
    result = {'message_id': None, 'in_reply_to': [], 'references': [],
              'from_address': '', 'subject': '', 'body_text': '', 'parse_error': None}
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
        ids = message.get_all('Message-ID', [])
        if len(ids) == 1 and MESSAGE_ID.fullmatch(str(ids[0]).strip()):
            result['message_id'] = str(ids[0]).strip()
        elif ids:
            result['parse_error'] = 'invalid_headers'
        for header, key in (('In-Reply-To', 'in_reply_to'), ('References', 'references')):
            value = ' '.join(str(item) for item in message.get_all(header, []))
            result[key] = list(dict.fromkeys(MESSAGE_ID.findall(value)))
            if MESSAGE_ID.sub('', value).strip():
                result['parse_error'] = 'invalid_headers'
        result['subject'] = str(message.get('Subject', '')).replace('\x00', '')
        result['from_address'] = parseaddr(str(message.get('From', '')))[1].replace('\x00', '')
        body = message.get_body(preferencelist=('plain',))
        if body is not None and body.get_content_disposition() != 'attachment':
            result['body_text'] = body.get_content().replace('\x00', '')
        if message.defects:
            result['parse_error'] = 'invalid_headers'
        if not result['body_text'].strip():
            result['parse_error'] = result['parse_error'] or 'unsupported_body'
    except (ValueError, LookupError, UnicodeError, TypeError):
        result['parse_error'] = 'parse_error'
    return result
