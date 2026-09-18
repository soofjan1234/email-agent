"""A4 双路知识召回：按来源隔离全文和向量候选，再以固定 RRF 基线融合。"""
import asyncio
from dataclasses import dataclass
import re
import time

import httpx
import numpy as np

from adapters.embedding import KnowledgeEmbedder
from evals.harness.normalize import extract_protected, normalize_query
from repositories.knowledge import keyword_search, vector_search


# MVP 固定 RRF 常量和每路候选量；没有保留集证据时不得调参。
RRF_K = 60
SOURCE_LIMIT = 3
CHANNEL_CANDIDATE_LIMIT = 20
SOURCE_TYPES = ('product_doc', 'approved_case')


class RetrievalError(Exception):
    """只向调用方返回固定模型错误，不传递查询或上游服务细节。"""

    def __init__(self, status, code, message):
        """保存 API 或后续 Graph 可消费的安全错误。"""
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


@dataclass(frozen=True)
class RetrievedChunk:
    """携带片段、来源版本和融合排名，供后续引用校验使用。"""
    chunk_id: str
    document_id: str
    source_type: str
    source_ref: str
    version: int
    title: str
    content: str
    product_model: str | None
    os_version: str | None
    category: str | None
    rank: int
    rrf_score: float
    keyword_rank: int | None
    vector_rank: int | None


@dataclass(frozen=True)
class RetrievalResult:
    """检索只给候选和可追溯排名，不把相似度偷换为依据充分结论。"""
    query: str
    normalized_tokens: list[str]
    protected_identifiers: list[str]
    query_metadata: dict[str, str | None]
    sources: dict[str, list[RetrievedChunk]]
    rrf_k: int
    evidence_assessed: bool
    has_reliable_evidence: bool


def extract_query_metadata(query):
    """只从已验证的受保护标识提取 DS 型号和 DSM 版本，未识别时保持空而非猜测。"""
    identifiers = extract_protected(query)
    product_model = next((value for value in identifiers if re.fullmatch(r'DS\d+\+', value)), None)
    os_version = next((value for value in identifiers if re.fullmatch(r'DSM\s+\d+\.\d+', value)), None)
    return identifiers, {'product_model': product_model, 'os_version': os_version}


class RetrievalService:
    """模型编码在数据库事务外完成；两条数据库通道读取同一有效版本集合。"""

    def __init__(self, database, embedding_factory=None):
        """默认使用 A3 已验证身份的查询角色适配器，测试只替换该外部边界。"""
        self.database = database
        self.embedding_factory = embedding_factory or (lambda: KnowledgeEmbedder(database.settings))

    def _query_vector(self, query):
        """先校验实际服务身份和固定维度；失败时不静默降级为关键词检索。"""
        embedding = self.embedding_factory()
        try:
            embedding.verify_identity()
            vectors = embedding.embed_queries([query])
            if len(vectors) != 1:
                raise ValueError('query embedding count mismatch')
            vector = np.asarray(vectors[0], dtype=np.float64)
            if (vector.shape != (self.database.settings.embedding_dimensions,) or not np.isfinite(vector).all()
                    or np.linalg.norm(vector) == 0):
                raise ValueError('invalid query embedding')
            return vector.tolist()
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise RetrievalError(503, 'retrieval_embedding_failed',
                                 'Knowledge retrieval embedding is unavailable; retry is safe') from None
        finally:
            embedding.close()

    @staticmethod
    def _fuse(source_type, keyword_rows, vector_rows):
        """对一个来源的两个排名列表做 RRF 去重；同片段只在该来源内累积贡献。"""
        candidates = {}

        def add(rows, channel):
            """记录通道名次和常量贡献，首次出现时固定片段及文档来源。"""
            for rank, (chunk, document, _) in enumerate(rows, 1):
                row = candidates.setdefault(str(chunk.id), {'chunk': chunk, 'document': document,
                                                            'score': 0.0, 'keyword_rank': None,
                                                            'vector_rank': None})
                row['score'] += 1 / (RRF_K + rank)
                row[channel] = rank

        add(keyword_rows, 'keyword_rank')
        add(vector_rows, 'vector_rank')
        ordered = sorted(candidates.values(), key=lambda row: (-row['score'],
                         min(value for value in (row['keyword_rank'], row['vector_rank']) if value is not None),
                         str(row['chunk'].id)))[:SOURCE_LIMIT]
        return [RetrievedChunk(chunk_id=str(row['chunk'].id), document_id=str(row['document'].id),
                               source_type=source_type, source_ref=row['document'].source_ref,
                               version=row['document'].version, title=row['document'].title,
                               content=row['chunk'].content, product_model=row['chunk'].product_model,
                               os_version=row['chunk'].os_version, category=row['chunk'].category,
                               rank=index, rrf_score=row['score'], keyword_rank=row['keyword_rank'],
                               vector_rank=row['vector_rank'])
                for index, row in enumerate(ordered, 1)]

    @staticmethod
    def _channel_rows(source_type, rows, channel):
        """把单通道原始排名映射为与 RRF 一致的受控片段对象。"""
        return [RetrievedChunk(chunk_id=str(chunk.id), document_id=str(document.id), source_type=source_type,
            source_ref=document.source_ref, version=document.version, title=document.title, content=chunk.content,
            product_model=chunk.product_model, os_version=chunk.os_version, category=chunk.category, rank=rank,
            rrf_score=0.0, keyword_rank=rank if channel == 'keyword' else None,
            vector_rank=rank if channel == 'vector' else None)
            for rank, (chunk, document, _) in enumerate(rows[:SOURCE_LIMIT], 1)]

    async def retrieve_product_channels(self, query):
        """评估专用只读入口：同一查询返回产品资料的关键词、向量和 RRF Top-3。"""
        if not isinstance(query, str) or not query.strip():
            raise RetrievalError(400, 'invalid_query', 'A non-empty knowledge query is required')
        # 1. 固定原查询、元数据过滤和候选上限，评估不允许查询改写。
        tokens = normalize_query(query)
        _, metadata = extract_query_metadata(query)
        started = time.perf_counter()
        vector = await asyncio.to_thread(self._query_vector, query)
        encoding_ms = round((time.perf_counter() - started) * 1000)
        async with self.database.session() as session:
            keyword_started = time.perf_counter()
            keyword_rows = await keyword_search(session, 'product_doc', tokens,
                self.database.settings.embedding_index_version, metadata['product_model'], metadata['os_version'],
                CHANNEL_CANDIDATE_LIMIT)
            keyword_ms = round((time.perf_counter() - keyword_started) * 1000)
            vector_started = time.perf_counter()
            vector_rows = await vector_search(session, 'product_doc', vector,
                self.database.settings.embedding_index_version, metadata['product_model'], metadata['os_version'],
                CHANNEL_CANDIDATE_LIMIT)
            vector_ms = round((time.perf_counter() - vector_started) * 1000)
        rrf_started = time.perf_counter()
        rrf_rows = self._fuse('product_doc', keyword_rows, vector_rows)
        rrf_ms = round((time.perf_counter() - rrf_started) * 1000)
        return {'keyword': self._channel_rows('product_doc', keyword_rows, 'keyword'),
                'vector': self._channel_rows('product_doc', vector_rows, 'vector'), 'rrf': rrf_rows,
                'durations_ms': {'query_embedding': encoding_ms, 'keyword': keyword_ms,
                                 'vector': vector_ms, 'rrf': rrf_ms},
                'query_metadata': metadata}

    async def retrieve(self, query):
        """按产品和案例分别执行全文/精确向量检索，再返回最多六个可引用候选。"""
        if not isinstance(query, str) or not query.strip():
            raise RetrievalError(400, 'invalid_query', 'A non-empty knowledge query is required')
        # 1. 规范化只服务全文检索；原查询保持不变并以查询角色生成向量。
        tokens = normalize_query(query)
        identifiers, metadata = extract_query_metadata(query)
        vector = await asyncio.to_thread(self._query_vector, query)
        # 2. 每个来源都走两条真实 PostgreSQL 通道，避免案例表达挤占产品事实。
        sources = {}
        async with self.database.session() as session:
            for source_type in SOURCE_TYPES:
                keyword_rows = await keyword_search(session, source_type, tokens,
                    self.database.settings.embedding_index_version, metadata['product_model'], metadata['os_version'],
                    CHANNEL_CANDIDATE_LIMIT)
                vector_rows = await vector_search(session, source_type, vector,
                    self.database.settings.embedding_index_version, metadata['product_model'], metadata['os_version'],
                    CHANNEL_CANDIDATE_LIMIT)
                sources[source_type] = self._fuse(source_type, keyword_rows, vector_rows)

        # 3. RRF 只产出候选；依据充分性必须由后续 Graph 结合风险和冲突单独判断。
        return RetrievalResult(query=query, normalized_tokens=tokens, protected_identifiers=identifiers,
                               query_metadata=metadata, sources=sources, rrf_k=RRF_K,
                               evidence_assessed=False, has_reliable_evidence=False)
