"""人工知识审核与原子发布：任何失败均回滚，不暴露半成品知识。"""
import asyncio
import hashlib
import json
from pathlib import Path, PureWindowsPath
import uuid

import httpx
import numpy as np
from sqlalchemy import select

from adapters.embedding import KnowledgeEmbedder
from evals.harness.redact import redact_case_text
from models import AuditEvent, CaseCandidate, HistoricalEmailPair, KnowledgeChunk, KnowledgeDocument
from repositories.knowledge import document_versions, lock_source
from services.chunking import split_markdown


class KnowledgeError(Exception):
    """领域错误只携带固定安全内容，模型响应和原文不进入 HTTP 错误。"""

    def __init__(self, status, code, message):
        """保存 HTTP 映射，不串联上游异常正文。"""
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


def conflict():
    """统一表示过期请求或不允许的状态迁移。"""
    return KnowledgeError(409, 'knowledge_state_conflict', 'Knowledge state or revision conflicts')


def clean(value, mail=False):
    """所有进入检索或响应的人工输入再次脱敏，文档保留 Markdown 引用。"""
    return redact_case_text(value, strip_mail_noise=mail)[0]


def serialize_candidate(candidate):
    """显式字段白名单排除原始审核文本和邮件正文。"""
    return {'id': str(candidate.id), 'email_pair_id': str(candidate.email_pair_id) if candidate.email_pair_id else None,
            'status': candidate.status, 'revision': candidate.revision,
            'user_symptom': candidate.user_symptom, 'applicability': candidate.applicability,
            'reply_template': candidate.reply_template, 'product_model': candidate.product_model,
            'os_version': candidate.os_version, 'category': candidate.category,
            'risk_tags': candidate.risk_tags, 'fact_sources': candidate.fact_sources,
            'reviewer': candidate.reviewer, 'review_comment': candidate.review_comment,
            'redaction_result': candidate.redaction_result,
            'published_document_id': str(candidate.published_document_id) if candidate.published_document_id else None}


def serialize_document(document):
    """只返回可追溯标识和脱敏元数据，不输出原文。"""
    return {'id': str(document.id), 'source_type': document.source_type, 'source_ref': document.source_ref,
            'title': document.title, 'version': document.version, 'status': document.status,
            'index_version': document.index_version, 'metadata': document.source_metadata}


class KnowledgeService:
    """数据库事务涵盖整次发布；同步模型操作移到线程，避免阻塞 API 事件循环。"""

    def __init__(self, database, embedding_factory=None, request_id=None):
        """每次发布创建独立模型客户端，测试仅替换模型边界。"""
        self.database = database
        self.embedding_factory = embedding_factory or (lambda: KnowledgeEmbedder(database.settings))
        self.request_id = request_id

    def audit(self, session, event, entity_id, reviewer=None):
        """记录操作和安全标识，审核原文在受控字段中保存。"""
        session.add(AuditEvent(event_type=event, actor_type='human', request_id=self.request_id,
                               data={'entity_id': str(entity_id), 'reviewer': clean(reviewer or '')}))

    async def _candidate(self, session, candidate_id):
        """先锁来源配对、再锁候选，保持确认、审核、发布、归档的统一锁顺序。"""
        pair_id = await session.scalar(select(CaseCandidate.email_pair_id).where(CaseCandidate.id == candidate_id))
        pair = None
        if pair_id:
            pair = await session.scalar(select(HistoricalEmailPair).where(
                HistoricalEmailPair.id == pair_id,
                HistoricalEmailPair.mailbox_id == self.database.settings.mailbox_id).with_for_update())
            if pair is None:
                raise KnowledgeError(404, 'not_found', 'Candidate not found')
        candidate = await session.scalar(select(CaseCandidate).where(CaseCandidate.id == candidate_id).with_for_update())
        if candidate is None:
            raise KnowledgeError(404, 'not_found', 'Candidate not found')
        return candidate, pair

    async def confirm_pair(self, pair_id, action, reviewer):
        """只确认 A2 已确定配对，重复确认复用其候选，拒绝后不能绕过审核。"""
        async with self.database.session() as session:
            pair = await session.scalar(select(HistoricalEmailPair).where(
                HistoricalEmailPair.id == pair_id,
                HistoricalEmailPair.mailbox_id == self.database.settings.mailbox_id).with_for_update())
            if pair is None:
                raise KnowledgeError(404, 'not_found', 'Pair not found')
            candidate = await session.scalar(select(CaseCandidate).where(
                CaseCandidate.email_pair_id == pair_id).with_for_update())
            if candidate is None or pair.pairing_method != 'header' or action not in ('confirm', 'reject'):
                raise conflict()
            target = 'paired' if action == 'confirm' else 'rejected'
            if pair.status != target:
                if (pair.status == 'rejected' or candidate.published_document_id
                        or candidate.status not in ('candidate', 'reviewed')):
                    raise conflict()
                pair.status = target
                if action == 'reject':
                    candidate.status = 'rejected'
                    candidate.revision += 1
                self.audit(session, 'case_pair_' + action, pair.id, reviewer)
            return {'id': str(pair.id), 'status': pair.status, 'candidate_id': str(candidate.id)}

    async def review(self, candidate_id, payload):
        """审核修订生成新的候选版本；已发布版本在新版本完成前继续有效。"""
        async with self.database.session() as session:
            candidate, pair = await self._candidate(session, candidate_id)
            if (candidate.revision != payload['expected_revision']
                    or candidate.status not in ('candidate', 'reviewed', 'active')
                    or (pair is not None and pair.status != 'paired')):
                raise conflict()
            action = payload['action']
            if action not in ('approve', 'reject') or (action == 'reject' and candidate.published_document_id):
                raise conflict()
            # 1. 事实来源与适用条件由人填写，不从邮件内容推测。
            if action == 'approve':
                fields = ('user_symptom', 'applicability', 'reply_template')
                if (any(not payload.get(field, '').strip() for field in fields) or not payload.get('fact_sources')
                        or any(not clean(value) for value in payload['fact_sources'])):
                    raise KnowledgeError(400, 'invalid_review', 'Review requires content, applicability and fact sources')
                values = {field: clean(payload[field], mail=True) for field in fields}
                if any(not value for value in values.values()):
                    raise KnowledgeError(400, 'invalid_review', 'Review content is empty after cleaning')
                for field, value in values.items():
                    setattr(candidate, field, value)
                for field in ('product_model', 'os_version', 'category'):
                    setattr(candidate, field, clean(payload[field]) if payload.get(field) else None)
                candidate.risk_tags = [clean(value) for value in payload.get('risk_tags', [])]
                candidate.fact_sources = [clean(value) for value in payload['fact_sources']]
            # 2. 原始人工输入只保存在受控列，审计事件和 API 仅返回脱敏结果。
            candidate.raw_review = dict(payload)
            candidate.reviewer = clean(payload['reviewer'])
            candidate.review_comment = clean(payload.get('comment') or '')
            candidate.redaction_result = {'rules_version': 'text-v1', 'requires_human_review': False}
            candidate.status = 'reviewed' if action == 'approve' else 'rejected'
            candidate.revision += 1
            self.audit(session, 'case_review_' + action, candidate.id, candidate.reviewer)
            await session.flush()
            return serialize_candidate(candidate)

    async def publish(self, candidate_id, expected_revision):
        """同一审核版本重复发布复用结果，未审核或过期请求明确拒绝。"""
        async with self.database.session() as session:
            candidate, pair = await self._candidate(session, candidate_id)
            if candidate.revision != expected_revision or (pair is not None and pair.status != 'paired'):
                raise conflict()
            if candidate.status == 'active' and candidate.published_document_id:
                return serialize_document(await session.get(KnowledgeDocument, candidate.published_document_id))
            if candidate.status != 'reviewed' or not candidate.fact_sources or not candidate.reviewer:
                raise conflict()
            # 完整问答同属一个文档版本，超长分片仍通过 candidate_id 和章节角色关联。
            title = 'Reviewed support case'
            markdown = '\n\n'.join(('# User symptom', candidate.user_symptom, '# Applicability',
                                      candidate.applicability, '# Reply', candidate.reply_template,
                                      '# Fact sources', '\n'.join(candidate.fact_sources)))
            metadata = {field: getattr(candidate, field) for field in ('product_model', 'os_version', 'category')}
            metadata.update(candidate_id=str(candidate.id), candidate_revision=candidate.revision,
                            fact_sources=candidate.fact_sources, risk_tags=candidate.risk_tags,
                            reviewer=candidate.reviewer, review_comment=candidate.review_comment)
            document = await self._publish(session, 'approved_case', str(candidate.id), title,
                                           markdown, json.dumps(candidate.raw_review, ensure_ascii=False), metadata)
            candidate.status, candidate.published_document_id = 'active', document.id
            self.audit(session, 'case_published', candidate.id, candidate.reviewer)
            return serialize_document(document)

    async def archive(self, candidate_id, expected_revision, reviewer):
        """归档当前有效案例并保留全部历史文档与片段，重复归档无额外副作用。"""
        async with self.database.session() as session:
            candidate, _ = await self._candidate(session, candidate_id)
            if candidate.revision != expected_revision:
                raise conflict()
            if candidate.status == 'archived':
                return serialize_candidate(candidate)
            if not candidate.published_document_id:
                raise conflict()
            document = await session.get(KnowledgeDocument, candidate.published_document_id)
            document.status = 'archived'
            candidate.status = 'archived'
            self.audit(session, 'case_archived', candidate.id, reviewer)
            await session.flush()
            return serialize_candidate(candidate)

    def _read_document(self, relative):
        """拒绝绝对路径、穿越、Windows 设备路径/数据流及工作区外链接。"""
        windows = PureWindowsPath(relative)
        normalized = relative.replace('\\', '/')
        parts = normalized.split('/')
        if (not relative or windows.drive or windows.root or ':' in relative or '\x00' in relative
                or any(part in ('', '.', '..') or part.endswith((' ', '.')) for part in parts)):
            raise KnowledgeError(400, 'invalid_path', 'A trusted relative Markdown path is required')
        try:
            root = self.database.settings.knowledge_root.resolve(strict=True)
            requested = root.joinpath(*parts)
            path = requested.resolve(strict=True)
            if not path.is_relative_to(root) or path.suffix.lower() != '.md' or not path.is_file():
                raise ValueError('outside trusted directory or unsupported format')
            # 不接受任何符号链接/目录联接，避免链接改变后读取不同信任域。
            cursor = requested
            while cursor != root:
                if cursor.is_symlink() or cursor.is_junction():
                    raise ValueError('linked source')
                cursor = cursor.parent
            with path.open('rb') as source:
                raw = source.read(self.database.settings.knowledge_max_bytes + 1)
            if len(raw) > self.database.settings.knowledge_max_bytes:
                raise ValueError('document too large')
            return path.relative_to(root).as_posix(), raw.decode('utf-8-sig')
        except (OSError, ValueError, RuntimeError):
            raise KnowledgeError(400, 'invalid_path', 'Cannot read a trusted UTF-8 Markdown document') from None

    async def import_document(self, path, title=None, product_model=None, os_version=None, category=None):
        """运行期间从固定可信根目录读取快照；相同内容和配置复用已发布版本。"""
        relative, raw = await asyncio.to_thread(self._read_document, path)
        title = clean(title or Path(relative).stem)
        markdown = clean(raw)
        metadata = {key: clean(value) if value else None for key, value in dict(
            product_model=product_model, os_version=os_version, category=category).items()}
        metadata['relative_path'] = relative
        source_ref = self.database.settings.knowledge_source_id + ':' + relative
        async with self.database.session() as session:
            document = await self._publish(session, 'product_doc', source_ref, title, markdown, raw, metadata)
            return serialize_document(document)

    def _prepare(self, markdown, title, cached):
        """先校验模型身份、切分及嵌入全部片段；任何异常只返回固定服务错误。"""
        embedder = self.embedding_factory()
        try:
            embedder.verify_identity()
            chunks = split_markdown(markdown, title, embedder.count_tokens, embedder.max_input_length)
            missing = list(dict.fromkeys(chunk.content for chunk in chunks if chunk.content not in cached))
            encoded = embedder.embed_documents(missing) if missing else []
            if len(encoded) != len(missing):
                raise ValueError('embedding count mismatch')
            cached.update(zip(missing, encoded, strict=True))
            vectors = [cached[chunk.content] for chunk in chunks]
            for vector in vectors:
                array = np.asarray(vector, dtype=np.float64)
                if (array.shape != (self.database.settings.embedding_dimensions,)
                        or not np.isfinite(array).all() or np.linalg.norm(array) == 0):
                    raise ValueError('invalid embedding vector')
            return chunks, vectors
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise KnowledgeError(503, 'knowledge_preparation_failed', 'Knowledge preparation failed; retry is safe') from None
        finally:
            embedder.close()

    async def _publish(self, session, source_type, source_ref, title, markdown, raw, metadata):
        """来源锁与版本切换同事务，旧版本只有在全部新片段成功后才归档。"""
        # 1. 同来源串行化；指纹包括元数据、切分算法版本以及索引身份。
        await lock_source(session, source_type, source_ref)
        index_version = self.database.settings.embedding_index_version
        fingerprint = hashlib.sha256(json.dumps({'title': title, 'markdown': markdown, 'metadata': metadata,
            'chunking': 'markdown-v1', 'identity': self.database.settings.embedding_identity()},
            ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        versions = await document_versions(session, source_type, source_ref)
        for version in versions:
            if version.status == 'active' and version.content_hash == fingerprint and version.index_version == index_version:
                return version
        # 2. 全部准备成功前，不写入可检索文档；线程不能访问数据库或持有事务对象。
        previous_chunks = (await session.scalars(select(KnowledgeChunk).join(KnowledgeDocument).where(
            KnowledgeDocument.source_type == source_type, KnowledgeDocument.source_ref == source_ref,
            KnowledgeChunk.index_version == index_version))).all()
        cached = {chunk.content: chunk.embedding for chunk in previous_chunks}
        chunks, vectors = await asyncio.to_thread(self._prepare, markdown, title, cached)
        document = KnowledgeDocument(source_type=source_type, source_ref=source_ref, title=title,
            version=versions[0].version + 1 if versions else 1, status='active', content_hash=fingerprint,
            index_version=index_version, source_metadata=metadata, raw_content=raw)
        session.add(document)
        await session.flush()
        for number, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            session.add(KnowledgeChunk(document_id=document.id, chunk_index=number, content=chunk.content,
                embedding=vector, index_version=index_version, section_path=chunk.section_path,
                source_metadata=metadata, token_count=chunk.token_count,
                **{key: metadata.get(key) for key in ('product_model', 'os_version', 'category')}))
        # 3. 向量写校验或提交失败时整个事务回滚，包含旧版本归档和候选状态。
        await session.flush()
        for version in versions:
            version.status = 'archived'
        self.audit(session, 'knowledge_version_published', document.id, metadata.get('reviewer'))
        return document
