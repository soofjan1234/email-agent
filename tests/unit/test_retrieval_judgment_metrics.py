"""验证抽检选样始终全量覆盖高风险初标并保持分层可复现。"""
from scripts.export_retrieval_audit_sample import select_audits


def test_audit_sampling_keeps_low_confidence_and_no_answer():
    """低置信度或 no_answer 不能被 10% 随机抽样遗漏。"""
    rows = [
        {'retrieval_observation_id': 'a', 'sample_source': 'real', 'channel': 'keyword',
         'codex_label': 'relevant', 'confidence': 2},
        {'retrieval_observation_id': 'b', 'sample_source': 'real', 'channel': 'keyword',
         'codex_label': 'no_answer', 'confidence': 5},
    ] + [{'retrieval_observation_id': f'n{index}', 'sample_source': 'synthetic_v2', 'channel': 'rrf',
          'codex_label': 'not_relevant', 'confidence': 5} for index in range(10)]
    selected = select_audits(rows, 7)
    assert {'a', 'b'}.issubset({row['retrieval_observation_id'] for row in selected})
    assert len(selected) == 3
