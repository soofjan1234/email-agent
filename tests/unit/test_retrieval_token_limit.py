"""保护全文检索构造不受长邮件分词数量影响。"""
import inspect

from repositories.knowledge import keyword_search


def test_keyword_query_has_fixed_token_cap():
    """长邮件只能使用固定数量的全文 token，避免深层 SQL 表达式。"""
    assert 'normalized_tokens = normalized_tokens[:16]' in inspect.getsource(keyword_search)
