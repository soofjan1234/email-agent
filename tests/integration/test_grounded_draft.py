"""B2 通过真实 checkpoint 验证有依据草稿及查询投影。"""
import uuid
from types import SimpleNamespace

from models import Email
from services.dispatch import WorkflowDispatcher
from services.retrieval import RetrievedChunk
from workflow.nodes import SafeDraftProcessor


class ProductRetrieval:
    """固定返回一个可引用产品片段。"""

    async def retrieve(self, query):
        chunk = RetrievedChunk(chunk_id='product-1', document_id='doc-1', source_type='product_doc',
            source_ref='product:test', version=1, title='SMB Guide', content='Enable SMB in Settings.',
            product_model=None, os_version=None, category='network', rank=1, rrf_score=1.0,
            keyword_rank=1, vector_rank=1)
        return SimpleNamespace(sources={'product_doc': [chunk], 'approved_case': []})


class GroundedGenerator:
    """返回只引用本轮产品片段的冻结 JSON。"""

    async def generate(self, messages):
        return {'category': 'network', 'priority': 'normal', 'risks': [],
                'knowledge_status': 'sufficient', 'reason': 'product documentation',
                'missing_information': [], 'citations': [{'chunk_id': 'product-1', 'usage': 'fact'}],
                'reply_draft': 'Please enable SMB in Settings.', 'requires_human_review': True}


async def test_grounded_draft_reaches_interrupt_and_projects_query_fields(database):
    """合法产品引用进入审核等待，并把列表字段作为可修复投影保存。"""
    email_id = uuid.uuid4()
    async with database.session() as session:
        session.add(Email(id=email_id, client_request_id=f'{database.settings.mailbox_id}:grounded:{email_id}',
            from_address='customer@example.test', subject='SMB unavailable', body_text='How do I enable SMB?',
            graph_thread_id=f'email:{email_id}:generation:1', workflow_generation=1))
    processor = SafeDraftProcessor(ProductRetrieval(), GroundedGenerator())
    snapshot = await WorkflowDispatcher(database, processor).dispatch_email(email_id)
    assert snapshot.next and snapshot.values['decision']['citations'][0]['chunk_id'] == 'product-1'
    async with database.session() as session:
        email = await session.get(Email, email_id)
        assert email.status == 'awaiting_review' and email.category == 'network'
        assert email.reply_draft == 'Please enable SMB in Settings.'
        assert email.citations == [{'chunk_id': 'product-1', 'usage': 'fact'}]
