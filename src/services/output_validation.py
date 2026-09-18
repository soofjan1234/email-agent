"""B2 后端输出校验：模型格式正确仍需验证引用来源与安全边界。"""
from evals.harness.agent_schema import AgentSchemaError, validate_agent_output


class OutputValidationError(ValueError):
    """模型输出不能安全进入人工审核等待。"""


def validate_grounded_output(payload, chunks):
    """验证冻结 Schema、引用集合和产品事实来源。"""
    try:
        result = validate_agent_output(payload)
    except AgentSchemaError as exc:
        raise OutputValidationError(str(exc)) from exc
    by_id = {chunk['chunk_id']: chunk for chunk in chunks}
    for citation in result['citations']:
        chunk = by_id.get(citation['chunk_id'])
        if chunk is None:
            raise OutputValidationError('citation_out_of_scope')
        if citation['usage'] == 'fact' and chunk['source_type'] != 'product_doc':
            raise OutputValidationError('case_cannot_support_product_fact')
    product_ids = {chunk['chunk_id'] for chunk in chunks if chunk['source_type'] == 'product_doc'}
    if result['knowledge_status'] == 'sufficient' and not product_ids:
        raise OutputValidationError('sufficient_without_product_evidence')
    if result['knowledge_status'] in ('high_risk', 'conflicting_evidence') and not result['requires_human_review']:
        raise OutputValidationError('unsafe_review_bypass')
    return result
