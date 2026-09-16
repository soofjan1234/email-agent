"""对完整邮件集合建立关联分量，拒绝从复杂会话中提取局部一对一。"""
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class PairingResult:
    """配对返回内部记录标识，未支持的每封邮件具有固定原因码。"""
    pairs: list
    reasons: dict


def identify_pairs(messages):
    """包括未知祖先和重复 Message-ID 的完整无向分量决定配对范围。"""
    by_key = defaultdict(list)
    links = defaultdict(set)
    # 1. 缺失 Message-ID 的记录使用内部节点，仍让其引用污染整个分量。
    for mail in messages:
        key = ('id', mail.message_id) if mail.message_id else ('record', str(mail.id))
        by_key[key].append(mail)
        links[key]
        for target in set(mail.in_reply_to + mail.references):
            neighbor = ('id', target)
            links[key].add(neighbor)
            links[neighbor].add(key)

    pairs, reasons, visited = [], {}, set()
    # 2. 连通分量包含整个会话；未扫描到的引用也保留为未知节点。
    for start in list(links):
        if start in visited:
            continue
        component, pending = set(), [start]
        while pending:
            key = pending.pop()
            if key in component:
                continue
            component.add(key)
            pending.extend(links[key] - component)
        visited.update(component)
        records = [mail for key in component for mail in by_key[key]]
        inbox = [mail for mail in records if mail.folder == 'inbox']
        sent = [mail for mail in records if mail.folder == 'sent']
        reason = None
        # 3. 不确定身份优先于关系数量；判定不依赖文件顺序或批次。
        if any(len(by_key[key]) > 1 for key in component):
            reason = 'duplicate_message_id'
        elif any(not mail.message_id for mail in records):
            reason = 'missing_message_id'
        elif any(mail.parse_error for mail in records):
            reason = 'invalid_message'
        elif any(not by_key[key] for key in component):
            reason = 'missing_reference'
        elif len(records) > 2:
            reason = 'complex_relationship'
        elif (len(inbox) == len(sent) == 1
              and inbox[0].message_id in sent[0].in_reply_to + sent[0].references
              and not inbox[0].in_reply_to and not inbox[0].references
              and sent[0].message_id not in sent[0].in_reply_to + sent[0].references):
            pairs.append((inbox[0].id, sent[0].id))
        else:
            reason = 'unmatched'
        if reason:
            reasons.update((mail.id, reason) for mail in records)
    return PairingResult(sorted(pairs, key=lambda pair: str(pair[0])), reasons)
