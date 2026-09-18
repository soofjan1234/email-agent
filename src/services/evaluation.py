"""评估运行的不可变审计服务，不参与 IMAP、SMTP 或审核提交。"""
import uuid

from sqlalchemy import select

from models import (Email, EvaluationRun, EvaluationSample, RetrievalJudgment,
                    RetrievalObservation)


class EvaluationError(Exception):
    """调用方违反评估冻结或输入契约时返回稳定原因码。"""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class EvaluationService:
    """集中执行运行创建、样本冻结和检索观察持久化的只增写入。"""

    def __init__(self, database):
        """绑定隔离数据库；服务本身不建立任何外部网络连接。"""
        self.database = database

    async def create_run(self, *, evaluation_run_id, purpose, knowledge_freeze_sha256, embedding_identity,
                         generator_identity=None, prompt_version=None, judge_model=None,
                         judge_prompt_version=None, judge_run_id=None, random_seed=0, code_version='unknown'):
        """创建或幂等读取完全相同的评估运行，不允许同 ID 改变身份。"""
        expected = dict(purpose=purpose, knowledge_freeze_sha256=knowledge_freeze_sha256,
            embedding_identity=embedding_identity, generator_identity=generator_identity,
            prompt_version=prompt_version, judge_model=judge_model, judge_prompt_version=judge_prompt_version,
            judge_run_id=judge_run_id, random_seed=random_seed, code_version=code_version)
        async with self.database.session() as session:
            current = await session.scalar(select(EvaluationRun).where(
                EvaluationRun.evaluation_run_id == evaluation_run_id))
            if current is not None:
                if any(getattr(current, key) != value for key, value in expected.items()):
                    raise EvaluationError('evaluation_run_immutable')
                return current
            if purpose not in ('retrieval', 'draft_latency', 'review') or len(knowledge_freeze_sha256) != 64:
                raise EvaluationError('invalid_evaluation_run')
            current = EvaluationRun(evaluation_run_id=evaluation_run_id, **expected)
            session.add(current)
            await session.flush()
            return current

    async def freeze_samples(self, evaluation_run_id, samples):
        """一次性冻结本运行的评估样本，之后禁止增删或替换来源邮件。"""
        seen = set()
        async with self.database.session() as session:
            run = await session.scalar(select(EvaluationRun).where(EvaluationRun.evaluation_run_id == evaluation_run_id))
            if run is None:
                raise EvaluationError('unknown_evaluation_run')
            if await session.scalar(select(EvaluationSample.id).where(EvaluationSample.evaluation_run_id == run.id)):
                raise EvaluationError('evaluation_samples_immutable')
            for sample in samples:
                email_id = sample.get('email_id')
                source = sample.get('sample_source')
                included = sample.get('included')
                reason = sample.get('exclusion_reason')
                if not isinstance(email_id, uuid.UUID) or email_id in seen or source not in ('real', 'synthetic_v2'):
                    raise EvaluationError('invalid_evaluation_sample')
                if not isinstance(included, bool) or (included and reason) or (not included and not reason):
                    raise EvaluationError('invalid_evaluation_sample')
                if await session.get(Email, email_id) is None:
                    raise EvaluationError('unknown_sample_email')
                seen.add(email_id)
                session.add(EvaluationSample(evaluation_run_id=run.id, email_id=email_id, sample_source=source,
                    included=included, exclusion_reason=reason))
            await session.flush()

    async def record_observations(self, evaluation_run_id, sample_id, channel, observations):
        """写入一个通道的固定 Top-K 或失败事实，拒绝重复通道和跨运行样本。"""
        if channel not in ('keyword', 'vector', 'rrf') or not observations:
            raise EvaluationError('invalid_retrieval_observations')
        async with self.database.session() as session:
            sample = await session.scalar(select(EvaluationSample).join(EvaluationRun).where(
                EvaluationRun.evaluation_run_id == evaluation_run_id, EvaluationSample.id == sample_id))
            if sample is None:
                raise EvaluationError('cross_run_sample')
            if await session.scalar(select(RetrievalObservation.id).where(
                    RetrievalObservation.evaluation_sample_id == sample.id, RetrievalObservation.channel == channel)):
                raise EvaluationError('retrieval_observations_immutable')
            ranks = set()
            for item in observations:
                rank, status = item.get('raw_rank'), item.get('status')
                if not isinstance(rank, int) or rank < 1 or rank in ranks or status not in ('succeeded', 'empty', 'failed', 'timed_out'):
                    raise EvaluationError('invalid_retrieval_observations')
                ranks.add(rank)
                session.add(RetrievalObservation(evaluation_sample_id=sample.id, channel=channel, raw_rank=rank,
                    candidate_chunk_id=item.get('candidate_chunk_id'), candidate_version=item.get('candidate_version'),
                    duration_ms=item.get('duration_ms', 0), status=status, failure_code=item.get('failure_code')))
            await session.flush()

    async def frozen_samples(self, evaluation_run_id):
        """只读加载已冻结样本及输入邮件，供运行器续跑缺失观察记录。"""
        async with self.database.session() as session:
            rows = await session.execute(select(EvaluationSample, Email).join(Email).join(EvaluationRun).where(
                EvaluationRun.evaluation_run_id == evaluation_run_id).order_by(EvaluationSample.created_at,
                EvaluationSample.id))
            return list(rows.all())

    async def pending_retrieval_samples(self, evaluation_run_id):
        """只返回尚未拥有三个通道事实的冻结样本，恢复运行不重复调用 Embedding。"""
        rows = await self.frozen_samples(evaluation_run_id)
        async with self.database.session() as session:
            observations = (await session.execute(select(EvaluationSample.id, RetrievalObservation.channel).join(
                RetrievalObservation).join(EvaluationRun).where(
                EvaluationRun.evaluation_run_id == evaluation_run_id))).all()
        completed = {}
        for sample_id, channel in observations:
            completed.setdefault(sample_id, set()).add(channel)
        return [(sample, email) for sample, email in rows
                if sample.included and completed.get(sample.id, set()) != {'keyword', 'vector', 'rrf'}]

    async def import_judgments(self, evaluation_run_id, *, judge_model, prompt_version, judge_run_id, judgments):
        """一次性导入完整 Codex 初标；judge 身份必须已在运行冻结，不能回填修改。"""
        if not all(isinstance(value, str) and value.strip()
                   for value in (judge_model, prompt_version, judge_run_id)):
            raise EvaluationError('invalid_judge_identity')
        labels = {'relevant', 'partially_relevant', 'not_relevant', 'no_answer'}
        async with self.database.session() as session:
            run = await session.scalar(select(EvaluationRun).where(EvaluationRun.evaluation_run_id == evaluation_run_id))
            if run is None:
                raise EvaluationError('unknown_evaluation_run')
            if (run.judge_model, run.judge_prompt_version, run.judge_run_id) != (
                    judge_model, prompt_version, judge_run_id):
                raise EvaluationError('judge_identity_not_frozen')
            observations = list((await session.scalars(select(RetrievalObservation.id).join(EvaluationSample).where(
                EvaluationSample.evaluation_run_id == run.id, EvaluationSample.included))).all())
            expected, supplied = set(observations), set()
            if await session.scalar(select(RetrievalJudgment.id).join(RetrievalObservation).join(EvaluationSample).where(
                    EvaluationSample.evaluation_run_id == run.id)):
                raise EvaluationError('retrieval_judgments_immutable')
            for judgment in judgments:
                observation_id = judgment.get('retrieval_observation_id')
                label, confidence, rationale = (judgment.get('label'), judgment.get('confidence'),
                                                judgment.get('rationale'))
                if (not isinstance(observation_id, uuid.UUID) or observation_id not in expected
                        or observation_id in supplied or label not in labels
                        or not isinstance(confidence, int) or not 1 <= confidence <= 5
                        or not isinstance(rationale, str) or not rationale.strip()):
                    raise EvaluationError('invalid_retrieval_judgment')
                supplied.add(observation_id)
            if supplied != expected:
                raise EvaluationError('incomplete_retrieval_judgments')
            for judgment in judgments:
                session.add(RetrievalJudgment(retrieval_observation_id=judgment['retrieval_observation_id'],
                    blinded_rank=judgment['blinded_rank'], codex_label=judgment['label'],
                    confidence=judgment['confidence'], rationale=judgment['rationale']))
            await session.flush()

    async def apply_audits(self, evaluation_run_id, audits):
        """追加人工抽检结论；只允许 pending 初标进入一次审核，不覆盖 Codex 标签。"""
        statuses = {'confirmed', 'corrected', 'unable_to_judge'}
        labels = {'relevant', 'partially_relevant', 'not_relevant', 'no_answer'}
        seen = set()
        async with self.database.session() as session:
            run = await session.scalar(select(EvaluationRun).where(EvaluationRun.evaluation_run_id == evaluation_run_id))
            if run is None:
                raise EvaluationError('unknown_evaluation_run')
            rows = list((await session.execute(select(RetrievalJudgment, RetrievalObservation).select_from(
                RetrievalJudgment).join(RetrievalObservation,
                RetrievalJudgment.retrieval_observation_id == RetrievalObservation.id).join(EvaluationSample,
                RetrievalObservation.evaluation_sample_id == EvaluationSample.id).where(
                EvaluationSample.evaluation_run_id == run.id))).all())
            by_observation = {observation.id: judgment for judgment, observation in rows}
            for audit in audits:
                observation_id, status, final_label = (audit.get('retrieval_observation_id'), audit.get('audit_status'),
                                                       audit.get('final_label'))
                judgment = by_observation.get(observation_id)
                if (not isinstance(observation_id, uuid.UUID) or observation_id in seen or judgment is None
                        or judgment.audit_status != 'pending' or status not in statuses
                        or (status == 'corrected' and final_label not in labels)
                        or (status != 'corrected' and final_label is not None)):
                    raise EvaluationError('invalid_retrieval_audit')
                seen.add(observation_id)
            for audit in audits:
                judgment = by_observation[audit['retrieval_observation_id']]
                judgment.audit_status, judgment.final_label = audit['audit_status'], audit.get('final_label')
            await session.flush()
