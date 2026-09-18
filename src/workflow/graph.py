"""唯一运行状态来源：B2 处理后在真实 LangGraph interrupt 等待 B3。"""
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import interrupt

from workflow.state import WorkflowState


def build_workflow(checkpointer, processor):
    """编译可恢复工作流；业务副作用不放在可重放 interrupt 节点中。"""
    async def process_email(state):
        """执行 B2 受限处理，所有有限次数由后端节点控制。"""
        return await processor.process(state)

    def await_review(state):
        """只暂停并接收审核决定，节点重放不会写业务表。"""
        review = interrupt({'email_id': state['email_id'], 'decision': state['decision']})
        return {'review': review, 'phase': 'reviewed'}

    def route_after_processing(state):
        """垃圾邮件结束，其余安全草稿统一等待人工审核。"""
        return 'end' if state.get('phase') == 'archived' else 'review'

    builder = StateGraph(WorkflowState)
    builder.add_node('process_email', process_email)
    builder.add_node('await_review', await_review)
    builder.add_edge(START, 'process_email')
    builder.add_conditional_edges('process_email', route_after_processing,
                                  {'review': 'await_review', 'end': END})
    builder.add_edge('await_review', END)
    return builder.compile(checkpointer=checkpointer)
