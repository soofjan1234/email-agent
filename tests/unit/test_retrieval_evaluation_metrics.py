"""验证评估专用检索入口不改变候选上限或跨入 approved_case。"""
from types import SimpleNamespace

from services.retrieval import RetrievalService


def test_channel_rows_keeps_top_three_and_raw_channel_rank():
    """单通道评估记录保留原始名次，且固定截断为 Top-3。"""
    rows = []
    for index in range(4):
        chunk = SimpleNamespace(id=f'chunk-{index}', product_model=None, os_version=None, category=None,
            content='controlled')
        document = SimpleNamespace(id=f'doc-{index}', source_ref='product:test', version=1, title='Product')
        rows.append((chunk, document, 0.0))
    candidates = RetrievalService._channel_rows('product_doc', rows, 'keyword')
    assert [item.rank for item in candidates] == [1, 2, 3]
    assert [item.keyword_rank for item in candidates] == [1, 2, 3]
    assert all(item.source_type == 'product_doc' and item.vector_rank is None for item in candidates)
