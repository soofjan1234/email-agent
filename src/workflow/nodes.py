"""B2 分类、检索、受限生成与后端校验。"""
from dataclasses import asdict
from pathlib import Path
import re

from services.output_validation import OutputValidationError, validate_grounded_output


# 有限循环由后端控制，模型不能自行增加重试次数。
MAX_GENERATION_ATTEMPTS = 2
MAX_RETRIEVAL_ATTEMPTS = 2
PROMPT_INJECTION = re.compile(r'ignore (all |the )?(previous|system)|reveal .*prompt', re.I)
SPAM_MARKERS = ('unsubscribe', 'limited offer', 'buy now')
SYSTEM_PROMPT = (Path(__file__).resolve().parents[1] / 'prompts' / 'agent.txt').read_text(encoding='utf-8')


class SafeDraftProcessor:
    """把外部检索与生成封装为一次可持久化 Graph 节点计算。"""

    def __init__(self, retrieval=None, generator=None, vip_addresses=()):
        """测试可注入固定边界；缺少模型时安全转人工，不生成确定方案。"""
        self.retrieval = retrieval
        self.generator = generator
        self.vip_addresses = {address.strip().lower() for address in vip_addresses if address.strip()}

    @staticmethod
    def _restricted(state, reason, knowledge_status='no_reliable_evidence'):
        """证据不足、风险或外部依赖失败时生成最小人工接管草稿。"""
        return {'category': 'other', 'priority': 'normal', 'risks': [reason],
                'knowledge_status': knowledge_status, 'reason': reason,
                'missing_information': [], 'citations': [],
                'reply_draft': '信息或依据不足，请由人工客服核实后回复。',
                'requires_human_review': True}

    @staticmethod
    def _chunks(result):
        """把检索对象压缩为可序列化且可校验的受控字段。"""
        chunks = []
        for source_type, rows in result.sources.items():
            for row in rows:
                item = asdict(row)
                chunks.append({'chunk_id': item['chunk_id'], 'source_type': source_type,
                               'title': item['title'], 'content': item['content'],
                               'source_ref': item['source_ref'], 'version': item['version']})
        return chunks

    async def process(self, state):
        """执行有限 B2 路径并返回进入审核所需的完整决定。"""
        text = f"{state.get('subject', '')}\n{state.get('body_text', '')}"
        lowered = text.lower()
        if any(marker in lowered for marker in SPAM_MARKERS):
            return {'phase': 'archived', 'category': 'other', 'priority': 'low', 'risk': 'spam',
                    'decision': self._restricted(state, 'spam'), 'retrieval_attempts': 0,
                    'query_rewrite_count': 0, 'generation_attempts': 0, 'validation_errors': []}
        if state.get('from_address', '').lower() in self.vip_addresses:
            decision = self._restricted(state, 'vip_manual_attention')
            return {'phase': 'awaiting_review', 'category': 'other', 'priority': 'urgent',
                    'risk': 'vip', 'decision': decision, 'retrieval_attempts': 0,
                    'query_rewrite_count': 0, 'generation_attempts': 0, 'validation_errors': []}
        if PROMPT_INJECTION.search(text):
            decision = self._restricted(state, 'prompt_injection', 'high_risk')
            return {'phase': 'awaiting_review', 'category': 'other', 'priority': 'high',
                    'risk': 'prompt_injection', 'decision': decision, 'retrieval_attempts': 0,
                    'query_rewrite_count': 0, 'generation_attempts': 0, 'validation_errors': []}
        if self.retrieval is None:
            decision = self._restricted(state, 'retrieval_unavailable')
            return {'phase': 'awaiting_review', 'category': 'other', 'priority': 'normal',
                    'risk': 'dependency_unavailable', 'decision': decision, 'retrieval_attempts': 0,
                    'query_rewrite_count': 0, 'generation_attempts': 0, 'validation_errors': []}
        # 1. 初始查询失败或无产品依据时最多再用主题改写一次。
        chunks, retrieval_attempts, rewrite_count = [], 0, 0
        queries = (text, state.get('subject', '').strip() or text)
        for index, query in enumerate(queries[:MAX_RETRIEVAL_ATTEMPTS]):
            retrieval_attempts += 1
            rewrite_count = index
            try:
                chunks = self._chunks(await self.retrieval.retrieve(query))
            except Exception:
                continue
            if any(chunk['source_type'] == 'product_doc' for chunk in chunks):
                break
        if not chunks:
            decision = self._restricted(state, 'retrieval_failed')
            return {'phase': 'awaiting_review', 'category': 'other', 'priority': 'normal',
                    'risk': 'dependency_unavailable', 'decision': decision,
                    'retrieval_attempts': retrieval_attempts, 'query_rewrite_count': rewrite_count,
                    'generation_attempts': 0, 'validation_errors': []}
        product_chunks = [chunk for chunk in chunks if chunk['source_type'] == 'product_doc']
        if not product_chunks or self.generator is None:
            reason = 'no_product_evidence' if not product_chunks else 'generator_unavailable'
            decision = self._restricted(state, reason)
            return {'phase': 'awaiting_review', 'category': 'other', 'priority': 'normal',
                    'risk': reason, 'decision': decision, 'retrieval_attempts': retrieval_attempts,
                    'query_rewrite_count': rewrite_count,
                    'generation_attempts': 0, 'validation_errors': []}
        # 2. 生成结果逐次执行后端校验，超过固定次数转人工。
        messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': text},
                    {'role': 'system', 'content': str(chunks)}]
        errors = []
        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            try:
                decision = validate_grounded_output(await self.generator.generate(messages), chunks)
                return {'phase': 'awaiting_review', 'category': decision['category'],
                        'priority': decision['priority'],
                        'risk': ','.join(decision['risks']) or 'none', 'decision': decision,
                        'retrieval_attempts': retrieval_attempts, 'query_rewrite_count': rewrite_count,
                        'generation_attempts': attempt,
                        'validation_errors': errors}
            except (OutputValidationError, ValueError, TypeError, KeyError) as exc:
                errors.append(str(exc))
        decision = self._restricted(state, 'generation_validation_failed')
        return {'phase': 'awaiting_review', 'category': 'other', 'priority': 'high',
                'risk': 'generation_validation_failed', 'decision': decision,
                'retrieval_attempts': retrieval_attempts, 'query_rewrite_count': rewrite_count,
                'generation_attempts': MAX_GENERATION_ATTEMPTS,
                'validation_errors': errors}
