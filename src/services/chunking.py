"""Markdown 章节和段落优先切分，超长段落通过真实 tokenizer 递归拆分。"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Chunk:
    """正文与检索上下文分开保存，便于验证没有截断正文。"""
    content: str
    body: str
    section_path: list[str]
    token_count: int


def split_markdown(markdown, title, count_tokens, max_tokens):
    """保留标题路径、段落和代码块；仅超限段落按句子、空白及字符兜底拆分。"""
    # 1. 解析 ATX 标题；围栏代码块中的井号不得改变章节。
    sections, headings, lines = [], [], []
    fence = None

    def flush():
        """固定当前章节正文，空标题也保留到下一段上下文。"""
        if lines:
            sections.append(([value for _, value in headings], '\n'.join(lines).strip()))
            lines.clear()

    for line in markdown.splitlines():
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif fence == marker[1][0]:
                fence = None
        heading = re.match(r'^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$', line) if fence is None and not marker else None
        if heading:
            flush()
            level = len(heading[1])
            headings = [(n, value) for n, value in headings if n < level]
            headings.append((level, heading[2]))
        else:
            lines.append(line)
    flush()

    # 2. 每段携带完整标题路径；不能容纳来源时显式拒绝而非截断标题。
    result = []
    for path, body in sections:
        if not body:
            continue
        labels = [title] + [value for value in path if value != title]
        prefix = ' > '.join(labels) + '\n\n'
        if count_tokens(prefix) >= max_tokens:
            raise ValueError('section context exceeds model input limit')

        def split(value):
            """先尝试整段；超限时优先靠近中点的句界、再空白、最后字符边界。"""
            count = count_tokens(prefix + value)
            if count <= max_tokens:
                return [Chunk(prefix + value, value, path, count)]
            if len(value) <= 1:
                raise ValueError('cannot fit a character with section context')
            boundaries = [m.end() for m in re.finditer(r'[.!?。！？]\s+', value)]
            boundaries = boundaries or [m.end() for m in re.finditer(r'\s+', value)]
            boundaries = [point for point in boundaries if 0 < point < len(value)]
            middle = min(boundaries, key=lambda point: abs(point - len(value) / 2)) if boundaries else len(value) // 2
            return split(value[:middle]) + split(value[middle:])

        paragraphs = re.split(r'\n\s*\n', body)
        pending = ''
        for paragraph in paragraphs:
            proposed = pending + '\n\n' + paragraph if pending else paragraph
            if count_tokens(prefix + proposed) <= max_tokens:
                pending = proposed
            else:
                if pending:
                    result.extend(split(pending))
                parts = split(paragraph)
                result.extend(parts[:-1])
                pending = parts[-1].body
        if pending:
            result.extend(split(pending))
    if not result:
        raise ValueError('document contains no body text')
    # 3. 同章节片段在预算允许时附带上一段末句；上下文不替代或截掉当前正文。
    contextual = []
    for index, chunk in enumerate(result):
        if index and result[index - 1].section_path == chunk.section_path:
            previous = re.split(r'(?<=[.!?。！？])\s+', result[index - 1].body.strip())[-1]
            if count_tokens(previous) <= max_tokens // 10:
                content = chunk.content + '\n\nPrevious context: ' + previous
                count = count_tokens(content)
                if count <= max_tokens:
                    chunk = Chunk(content, chunk.body, chunk.section_path, count)
        contextual.append(chunk)
    return contextual
