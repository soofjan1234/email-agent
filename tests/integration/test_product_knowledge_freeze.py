"""验证官方产品资料冻结前的完整性约束。"""
from types import SimpleNamespace

import pytest

from scripts.freeze_product_knowledge import artifact_path, validate_documents
from scripts.import_product_knowledge import PRODUCT_DOCUMENTS


def document(content_hash='hash', metadata=None):
    """构造不依赖数据库的产品文档审计记录。"""
    return SimpleNamespace(content_hash=content_hash, source_metadata=metadata or {
        'official_url': 'https://example.invalid/support', 'retrieved_at': '2026-09-18',
        'applicable_models': 'E1', 'applicable_scope': 'test'})


def test_product_manifest_is_exactly_eight_official_documents():
    """导入清单必须是唯一来源，并在冻结允许范围内。"""
    assert len(PRODUCT_DOCUMENTS) == 8
    assert all(item[3].startswith('https://') and item[4] for item in PRODUCT_DOCUMENTS)


@pytest.mark.parametrize('documents, error', [
    ([document(str(index)) for index in range(3)], 'product_document_count_out_of_range'),
    ([document('same') for _ in range(8)], 'duplicate_or_missing_content_hash'),
    ([document(str(index), {'official_url': 'https://example.invalid'}) for index in range(8)],
     'missing_official_source_metadata'),
])
def test_freeze_rejects_incomplete_or_untraceable_documents(documents, error):
    """资料数量、内容和官方元数据任一不合格时不能进入评估冻结。"""
    with pytest.raises(ValueError, match=error):
        validate_documents(documents)


def test_freeze_path_rejects_parent_traversal(tmp_path):
    """冻结 ID 不能逃逸受控评估产物目录。"""
    with pytest.raises(ValueError, match='invalid_freeze_id'):
        artifact_path('../unsafe', tmp_path)
