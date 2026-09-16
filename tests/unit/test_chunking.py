"""按真实计数接口验证语义切分与完整保留，不依赖外部模型。"""
import pytest

from services.chunking import split_markdown


def test_sections_and_paragraphs_keep_source():
    """标题层级随每个片段保存，短段落不任意截断。"""
    chunks = split_markdown('# Guide\n\nIntro.\n\n## SMB\n\nCheck SMB.\n\nRestart service.',
                            'Guide', len, 100)
    assert any(c.section_path == ['Guide', 'SMB'] for c in chunks)
    assert 'Check SMB.' in '\n'.join(c.content for c in chunks)
    assert all(c.token_count <= 100 for c in chunks)


def test_long_paragraph_keeps_every_character():
    """超长无空格段落也完整切分，不静默截断尾部。"""
    body = '甲乙丙丁' * 200 + 'TAIL'
    chunks = split_markdown('# Guide\n\n' + body, 'Guide', len, 80)
    assert len(chunks) > 1
    assert ''.join(c.body for c in chunks) == body
    assert all(c.token_count <= 80 and c.section_path == ['Guide'] for c in chunks)


def test_code_fence_heading_is_not_section():
    """代码块中的井号不是 Markdown 章节。"""
    chunks = split_markdown('# Guide\n\n```sh\n# comment\necho hello\n```', 'Guide', len, 100)
    assert all(c.section_path == ['Guide'] for c in chunks)
    assert '# comment' in '\n'.join(c.content for c in chunks)


def test_unrepresentable_context_fails_explicitly():
    """标题本身超出输入预算时显式失败，而不是丢弃来源。"""
    with pytest.raises(ValueError):
        split_markdown('# ' + 'title' * 30 + '\n\nbody', 'Guide', len, 30)

