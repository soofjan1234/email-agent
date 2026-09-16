"""全量关联识别必须排除局部批次看似一对一的复杂会话。"""
from dataclasses import dataclass, field

import pytest

from services.pairing import identify_pairs


@dataclass
class Mail:
    """完整关系识别所需的最小邮件视图。"""
    id: str
    folder: str
    message_id: str | None
    in_reply_to: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    parse_error: str | None = None
    body_text: str = 'message'


def test_only_complete_one_to_one_is_a_pair():
    """协议头直接关联的一封收件和一封回复可生成候选。"""
    result = identify_pairs([Mail('a', 'inbox', '<a>'), Mail('b', 'sent', '<b>', ['<a>'])])
    assert result.pairs == [('a', 'b')]
    assert result.reasons == {}


@pytest.mark.parametrize('mails,reason', [
    ([Mail('a', 'inbox', '<a>'), Mail('b', 'sent', '<b>', ['<a>']),
      Mail('c', 'sent', '<c>', ['<a>'])], 'complex_relationship'),
    ([Mail('a', 'inbox', '<a>'), Mail('b', 'inbox', '<b>'),
      Mail('c', 'sent', '<c>', ['<a>', '<b>'])], 'complex_relationship'),
    ([Mail('a', 'inbox', '<a>'), Mail('b', 'inbox', '<b>', references=['<a>']),
      Mail('c', 'sent', '<c>', ['<b>']), Mail('d', 'sent', '<d>', ['<a>'])], 'complex_relationship'),
    ([Mail('a', 'inbox', '<a>'), Mail('b', 'sent', '<b>', ['<a>']),
      Mail('c', 'inbox', '<c>', references=['<a>', '<b>']),
      Mail('d', 'sent', '<d>', ['<c>'])], 'complex_relationship'),
    ([Mail('a', 'inbox', '<a>'), Mail('b', 'sent', '<b>', ['<a>'], ['<missing>', '<a>'])], 'missing_reference'),
    ([Mail('a', 'inbox', '<a>'), Mail('a2', 'inbox', '<a>'),
      Mail('b', 'sent', '<b>', ['<a>'])], 'duplicate_message_id'),
    ([Mail('a', 'inbox', '<a>'), Mail('b', 'sent', None, ['<a>'])], 'missing_message_id'),
])
def test_complex_or_uncertain_component_never_becomes_pair(mails, reason):
    """重复标识、多跳与未知祖先影响整个关联分量，不能抽出局部边。"""
    result = identify_pairs(mails)
    assert result.pairs == []
    assert set(result.reasons) == {mail.id for mail in mails}
    assert set(result.reasons.values()) == {reason}


def test_no_headers_and_empty_mailbox():
    """无关系的邮件保留未匹配原因，空邮箱可以正常结束。"""
    assert identify_pairs([]).pairs == []
    result = identify_pairs([Mail('a', 'inbox', '<a>'), Mail('b', 'sent', '<b>')])
    assert result.pairs == []
    assert result.reasons == {'a': 'unmatched', 'b': 'unmatched'}
