"""B1—B3 共用的可持久化 Graph 状态契约。"""
from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    """只保存恢复所需状态；数据库业务事实通过稳定 ID 引用。"""
    email_id: str
    workflow_generation: int
    from_address: str
    subject: str
    body_text: str
    category: str
    priority: str
    risk: str
    phase: str
    decision: dict[str, Any]
    retrieval_attempts: int
    query_rewrite_count: int
    generation_attempts: int
    validation_errors: list[str]
    review: dict[str, Any]
