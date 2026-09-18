"""验证未标注运行只输出非质量指标，且 Markdown 不包含原始邮件字段。"""
from scripts.report_retrieval_evaluation import render_markdown


def test_incomplete_report_omits_quality_claims_and_private_content():
    """没有完整标签时报告必须明确不可用，不把延迟写成相关性结论。"""
    report = {'evaluation_run_id': 'run-1', 'knowledge_freeze_sha256': 'a' * 64, 'sample_count': 1,
              'quality_ready': False, 'sources': {'overall': {'keyword': {'observation_count': 1,
              'succeeded_count': 1, 'empty_count': 0, 'failed_count': 0, 'timed_out_count': 0,
              'p50_ms': 1, 'p95_ms': 1, 'max_ms': 1}}, 'real': {}, 'synthetic_v2': {}}}
    rendered = render_markdown(report)
    assert '质量指标未输出' in rendered
    assert 'Recall' not in rendered and '@' not in rendered
