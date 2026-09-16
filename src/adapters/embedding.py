"""业务 TEI 适配器：复用身份及向量验证，使用同一模型 tokenizer 严格计数。"""
import httpx

from evals.harness.local_embedding import TeiEmbedder


class KnowledgeEmbedder(TeiEmbedder):
    """一次发布独占客户端，调用结束关闭，不共享可变计数缓存。"""

    def __init__(self, settings, client=None):
        """不继承系统代理或网关凭据；模型请求仍使用已有超时及单输入限制。"""
        owned = client is None
        super().__init__(settings.local_model(), settings.embedding_base_url,
                         client=client or httpx.Client(timeout=180, trust_env=False))
        self._owns_client = owned
        self.max_input_length = None
        self._counts = {}

    def verify_identity(self):
        """输入上限必须由实际加载模型报告，不能猜测 tokenizer 预算。"""
        info = super().verify_identity()
        limit = info.get('max_input_length')
        if type(limit) is not int or limit <= 0:
            raise ValueError('missing model input limit')
        self.max_input_length = limit
        return info

    def count_tokens(self, value):
        """计入文档前缀和特殊 token；/tokenize 返回完整编码，不使用截断。"""
        if value not in self._counts:
            response = self._client.post(self.config.base_url.rstrip('/') + '/tokenize', json={
                'inputs': [self.model.document_prefix + value], 'add_special_tokens': True})
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or len(rows) != 1:
                raise ValueError('invalid tokenizer batch')
            tokens = rows[0]
            if not isinstance(tokens, list) or not tokens or any(
                    not isinstance(token, dict) or type(token.get('id')) is not int for token in tokens):
                raise ValueError('invalid tokenizer response')
            self._counts[value] = len(tokens)
        return self._counts[value]

    def embed_documents(self, texts):
        """发送前核对真实 token 上限；底层 /embed 继续显式禁止截断。"""
        if self.max_input_length is None:
            raise ValueError('model identity has not been verified')
        if any(self.count_tokens(value) > self.max_input_length for value in texts):
            raise ValueError('document exceeds model input limit')
        return super().embed_documents(texts)
