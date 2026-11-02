from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext

from fastapi.encoders import jsonable_encoder

from ..agents import Debater, Moderator
from ..audit import AuditedLLM, RunAudit, selected_models
from ..data.base import DataUnavailable
from ..debate import Debate, verification_stats
from ..events import EventLog
from ..llm import LLM, LLMError
from ..rag.context import execution_policy
from ..single import SingleAnalyst
from ..snapshot import Snapshot
from .errors import ApiError
from .store import Store

log = logging.getLogger(__name__)


class LiveRunner:
    def __init__(self, settings, *, budget=None):
        self.settings = settings
        self.clients = []
        self.audit = None
        self.background_context = None
        self.budget = budget
        self.budget_scopes = set()

    def new_client(self, model, scope):
        if self.budget is not None:
            self.budget_scopes.add(scope)
            return LLM(model, budget=self.budget, budget_scope=scope)
        return LLM(model)

    @property
    def usage_complete(self):
        return all(getattr(client, 'usage_complete', True) for client in self.clients)

    def usage(self):
        totals = {}
        for client in self.clients:
            for call in client.usage_payload()['calls']:
                model = call['model']
                totals.setdefault(model, {'model': model})
                for key, value in call.items():
                    if key != 'model':
                        totals[model][key] = totals[model].get(key, 0) + value
        usage = {'calls': list(totals.values())}
        if self.budget is not None:
            cost = self.budget.cost_for_scopes(self.budget_scopes)
            if cost is not None:
                usage['cost_usd'] = cost
        return usage

    def run(self, snapshot, debate_id, max_extra_rounds, emit):
        settings = self.settings
        models = self.audit.data['config']['selected_models'] if self.audit else selected_models(settings)

        def client(role):
            with self.audit.stage(f'{role}_client_initialization') if self.audit else nullcontext():
                llm = self.new_client(models[role], f'{debate_id}:{role}')
                self.clients.append(llm)
                return AuditedLLM(llm, self.audit, role) if self.audit else llm

        debater_llm = client('debater')
        moderator_llm = client('moderator')
        result = Debate(snapshot, Debater(debater_llm, snapshot, effort=settings.debater_effort,
                                         background_context=self.background_context),
                        Moderator(moderator_llm, snapshot, effort=settings.moderator_effort,
                                  background_context=self.background_context),
                        EventLog(settings.debate_dir / f'{debate_id}.jsonl'), debate_id=debate_id,
                        max_extra_rounds=max_extra_rounds, on_event=emit).run()
        verdict = result.verdict.model_dump(mode='json')
        verdict['scores'] = {side: verdict.pop(side) for side in ('bull', 'bear')}
        verdict.pop('action')
        verdict.pop('extra_question')
        return {'debate_id': debate_id, 'verdict': verdict, 'stats': verification_stats(result.turns)}

    def close(self):
        for client in self.clients:
            client.client.close()

    def run_single(self, snapshot, debate_id, emit):
        models = self.audit.data['config']['selected_models'] if self.audit else selected_models(self.settings)
        with self.audit.stage('moderator_client_initialization') if self.audit else nullcontext():
            llm = self.new_client(models['moderator'], f'{debate_id}:single')
            self.clients.append(llm)
            wrapped = AuditedLLM(llm, self.audit, 'moderator') if self.audit else llm
        emit('moderator_started', {})
        verdict = SingleAnalyst(wrapped, snapshot, effort=self.settings.moderator_effort,
                                background_context=self.background_context).evaluate(
            EventLog(self.settings.debate_dir / f'{debate_id}.jsonl'))
        return {'debate_id': debate_id, 'verdict': {**verdict.model_dump(mode='json'), 'scores': None}, 'stats': None}


class Service:
    def __init__(self, settings, market, *, runner_factory=None, max_running=2):
        self.settings, self.market = settings, market
        self.max_running = max_running
        self.store = Store(settings.data_dir / 'http')
        self.budget = None
        try:
            budget_path = settings.data_dir / 'http' / 'provider-budget.sqlite3'
            if settings.worker_budget_usd is not None or settings.worker_budget_id is not None:
                from ..anthropic_budget import WorkerSpendLedger
                self.budget = WorkerSpendLedger(budget_path,
                                               settings.worker_budget_id, settings.worker_budget_usd)
                # Store now holds the directory's exclusive process lock, so no
                # previous owner can still be dispatching these reservations.
                self.budget.recover_interrupted()
            elif budget_path.exists():
                from ..anthropic_budget import BudgetDenied
                raise BudgetDenied('Existing worker budget requires its original configuration')
        except BaseException:
            self.store.close()
            raise
        self.runner_factory = runner_factory or (lambda: LiveRunner(settings, budget=self.budget))
        self.pool = ThreadPoolExecutor(max_workers=max_running, thread_name_prefix='debate')
        self.selection_policy = None
        if settings.rag_enabled and settings.rag_selection_policy:
            from ..rag.selection import SelectionPolicy
            self.selection_policy = SelectionPolicy.model_validate_json(settings.rag_selection_policy.read_text(encoding='utf-8'))
        self.shadow = None
        if settings.rag_shadow_enabled and settings.rag_enabled:
            from ..rag.shadow import ShadowRunner
            self.shadow = ShadowRunner(settings)

    def close(self):
        self.pool.shutdown(wait=True)
        if self.shadow is not None:
            self.shadow.close()
        self.store.close()

    def capture_generation(self, snapshot):
        from ..rag.binding import capture_binding, unavailable_binding
        from ..rag.archive_repository import configured_archive
        generation = self.settings.rag_generation_id
        if self.settings.rag_enabled:
            try:
                with configured_archive(self.settings) as archive:
                    return capture_binding(archive, snapshot, generation)
            except Exception:
                # Preserve the original snapshot and persist a closed route. The
                # retrieval stage records failure before any model is initialized.
                log.warning('snapshot publication binding unavailable')
        return unavailable_binding(snapshot, generation)

    def rag_lookup(self, body):
        """Read a frozen snapshot; never collect data, start a runner or submit shadow."""
        if not self.settings.rag_enabled:
            raise ApiError(503, 'RAG_DISABLED', 'RAG 조회가 비활성 상태입니다')
        from ..rag.evidence import parse_request
        from ..rag.retrieval import Retriever
        from ..rag.selection import SelectionPolicy
        from ..rag.archive_repository import configured_archive
        from ..rag.context_repository import configured_repository
        snapshot = Snapshot.model_validate(self.store.snapshot(body.snapshot_id))
        request = parse_request(body.model_dump(exclude={'snapshot_id'}))
        binding = (self.store.generation_binding(snapshot.snapshot_id) or {'state': 'unbound'}) if request.mode == 'documents' else None
        with configured_archive(self.settings) as archive:
            context = Retriever(archive, context_repository=configured_repository(self.settings),
                selection_policy=self.selection_policy or SelectionPolicy()).retrieve(snapshot,
                    generation_id=binding.get('generation_id', '') if binding else '', request=request,
                    generation_binding=binding)
        payload = context.payload
        if payload['status'] not in {'completed', 'empty'}:
            raise ApiError(503, 'RETRIEVAL_UNAVAILABLE', '검색을 완료하지 못했습니다')
        evidence = payload['evidence']
        response = {'snapshot_id': snapshot.snapshot_id, 'context_id': context.context_id,
                'ticker': snapshot.ticker, 'snapshot_as_of': snapshot.as_of.isoformat(),
                'mode': evidence['mode'], 'answerability': payload['answerability'],
                'reasons': evidence['reasons'] or ([payload['abstention_reason']]
                    if payload.get('abstention_reason') else []),
                }
        if request.mode == 'facts':
            response['facts'] = evidence['facts']
        else:
            response['documents'] = [{k: item[k] for k in ('chunk_id', 'text', 'horizons', 'applicability', 'limitations')}
                                     for item in payload['items']]
            response['answer_scope'] = 'retrieved_documents_not_verified_numeric_answer'
        return response

    def create(self, body):
        identity = {'ticker': body.ticker, 'max_extra_rounds': body.max_extra_rounds}
        # Preserve fingerprints for pre-v0.6 and explicit default requests.
        if body.mode != 'debate' or body.snapshot_id is not None:
            identity.update(mode=body.mode, snapshot_id=body.snapshot_id)
        fingerprint = json.dumps(identity, sort_keys=True)
        existing = self.store.request(body.request_id, fingerprint)
        if existing:
            return self.response(existing, True)
        snapshot, quote = None, None
        if body.snapshot_id is not None:
            snapshot = Snapshot.model_validate(self.store.snapshot(body.snapshot_id))
            if snapshot.ticker != body.ticker:
                raise ApiError(400, 'INVALID_REQUEST', '스냅샷과 요청 종목이 다릅니다')
            data_date = snapshot.as_of.isoformat()
        else:
            quote = self.market.quote(body.ticker)
            if quote.reasons:
                raise ApiError(422, 'NOT_ELIGIBLE', '토론할 수 없는 종목입니다', reasons=quote.reasons)
            data_date = quote.bars[-1].date.isoformat()
        row, reused = self.store.create(body.request_id, fingerprint, body.ticker,
                                        data_date, self.max_running, mode=body.mode, snapshot_id=body.snapshot_id)
        if not reused:
            try:
                self.pool.submit(self.run, row['id'], quote, body.max_extra_rounds, mode=body.mode, snapshot=snapshot)
            except RuntimeError:
                # The durable request already exists; finish it so retries keep
                # their identity and the capacity slot cannot remain occupied.
                self.store.emit(row['id'], 'debate_failed', {
                    'error': {'code': 'INTERNAL_ERROR', 'message': '토론 작업을 시작하지 못했습니다. 새 요청으로 재시도하세요.'}})
                row = self.store.get(row['id'])
        return self.response(row, reused)

    @staticmethod
    def response(row, reused):
        return {'debate_id': row['id'], 'snapshot_id': row['snapshot_id'], 'status': row['status'], 'reused': reused}

    def run(self, debate_id, quote, max_extra_rounds, *, mode='debate', snapshot=None):
        runner = None
        audit = None

        def collect_usage():
            try:
                if not getattr(runner, 'usage_complete', True):
                    raise RuntimeError('incomplete provider usage')
                if audit is not None and (not audit.data['usage_complete'] or any(
                    (call['status'] == 'running' or (call['status'] == 'failure' and not call.get('dispatch_blocked')))
                    for call in audit.data['llm_calls'])):
                    # One structured call may include tool follow-ups. Even a
                    # nonempty failure delta cannot account for its last request.
                    raise RuntimeError('incomplete provider usage')
                return runner.usage()
            except Exception as exc:
                log.warning('debate %s usage unavailable (%s)', debate_id, type(exc).__name__)
                if audit is not None:
                    try:
                        audit.usage_error(exc)
                    except OSError:
                        log.warning('debate %s usage audit persistence failed', debate_id)
                # Partial audit usage stays private. An empty/partial public
                # payload would make Spring settle unknown charges as final.
                return None

        try:
            audit = RunAudit(self.settings.data_dir, debate_id, ticker=snapshot.ticker if snapshot else quote.ticker,
                             data_date=snapshot.as_of.isoformat() if snapshot else quote.bars[-1].date.isoformat(),
                             max_extra_rounds=0 if mode == 'single' else max_extra_rounds,
                             mode=mode, models=selected_models(self.settings),
                             efforts={'debater': self.settings.debater_effort,
                                      'moderator': self.settings.moderator_effort},
                             secrets=(self.settings.dart_api_key, self.settings.krx_api_key,
                                      self.settings.naver_client_id, self.settings.naver_client_secret))
            with audit.stage('snapshot'):
                snapshot = snapshot if snapshot is not None else self.market.snapshot(quote)
                self.store.save_snapshot(debate_id, snapshot, binding_factory=self.capture_generation)
                # A content-addressed ID may already exist with an earlier
                # observation cutoff. Both modes must use the stored object.
                snapshot = Snapshot.model_validate(self.store.snapshot(snapshot.snapshot_id))
                audit.attach_snapshot(snapshot)
            self.store.emit(debate_id, 'snapshot_created', dict(snapshot_id=snapshot.snapshot_id,
                            ticker=snapshot.ticker, name=snapshot.name, as_of=snapshot.as_of,
                            close=snapshot.facts['PX.CLOSE'].value, warnings=snapshot.warnings))
            background_context = None
            retrieval_config = {'enabled': self.settings.rag_enabled,
                                'context_backend': self.settings.rag_context_backend,
                                'archive_backend': self.settings.rag_archive_backend,
                                'object_backend': self.settings.rag_object_backend,
                                'generation_id': self.settings.rag_generation_id,
                                'profile': self.settings.rag_profile}
            if self.settings.rag_enabled:
                with audit.stage('knowledge_context'):
                    binding = self.store.generation_binding(snapshot.snapshot_id) or {'state': 'unbound'}
                    generation = binding.get('generation_id', '')
                    retrieval_config['generation_id'] = generation
                    if not generation:
                        raise ValueError('snapshot has no pinned generation')
                    if self.settings.rag_profile != 'knowledge-short-v1':
                        raise ValueError('unsupported RAG profile')
                    from ..rag.retrieval import Retriever
                    from ..rag.context_repository import configured_repository
                    from ..rag.archive_repository import configured_archive
                    with configured_archive(self.settings) as rag_store:
                        repository = configured_repository(self.settings)
                        retriever = (Retriever(rag_store) if repository is None and self.selection_policy is None else
                                     Retriever(rag_store, context_repository=repository, selection_policy=self.selection_policy))
                        background_context = retriever.retrieve(
                            snapshot, generation_id=generation, generation_binding=binding)
            if self.selection_policy:
                retrieval_config['selection_policy_id'] = self.selection_policy.policy_id
            policy = execution_policy(background_context)
            retrieval_config['execution'] = policy
            # Keep the failed/empty retrieval evidence even when no background is
            # passed to the model. Persistence failure must prevent paid calls.
            audit.attach_context(background_context, retrieval_config=retrieval_config)
            if policy['action'] == 'abort':
                raise RuntimeError('knowledge retrieval did not complete')
            if self.shadow is not None:
                try:
                    self.shadow.submit(debate_id, snapshot, background_context, generation)
                except Exception:
                    log.warning('shadow submission failed')
            if policy['action'] != 'use_context':
                background_context = None
            with audit.stage('runner_initialization'):
                runner = self.runner_factory()
                if isinstance(runner, LiveRunner):
                    runner.audit = audit
                if hasattr(runner, 'background_context'):
                    runner.background_context = background_context
                audit.attach_runner(runner)

            def emit(event, payload):
                # Never forward raw tokens or private moderator/audit events.
                audit.observe_event(event, payload)
                if mode == 'single' and event != 'moderator_started':
                    return
                data = jsonable_encoder(payload)
                if event == 'statement_accepted':
                    if not data['verified']:
                        raise LLMError('재시도 후에도 근거 검증에 실패했습니다')
                    data['warnings'] = [i for i in data.pop('verification')['issues'] if i['severity'] == 'warning']
                elif event == 'tool_call':
                    data = {'side': data['side'], 'tool': data.get('tool', data.get('name'))}
                elif event not in ('turn_started', 'statement_rejected', 'extra_round_requested', 'moderator_started'):
                    return
                self.store.emit(debate_id, event, data)

            with audit.stage(mode):
                completed = (runner.run_single(snapshot, debate_id, emit) if mode == 'single' else
                             runner.run(snapshot, debate_id, max_extra_rounds, emit))
            usage = collect_usage()
            audit.finish('success', usage=usage, result=completed)
            self.store.emit(debate_id, 'debate_completed', {
                **completed, **({'usage': usage} if usage is not None else {})})
        except Exception as exc:
            # Provider exception strings may contain API keys. Keep public errors generic.
            code = 'DATA_UNAVAILABLE' if isinstance(exc, DataUnavailable) or runner is None else 'LLM_ERROR'
            log.warning('debate %s failed (%s)', debate_id, type(exc).__name__)
            payload = {'error': {'code': code, 'message': '데이터 조회에 실패했습니다' if code == 'DATA_UNAVAILABLE' else 'AI 토론을 완료하지 못했습니다'}}
            if runner is not None:
                usage = collect_usage()
                if usage is not None:
                    payload['usage'] = usage
            if audit is not None:
                try:
                    audit.finish('failure', usage=payload.get('usage'), error=exc)
                except OSError:
                    log.warning('debate %s audit persistence failed', debate_id)
            self.store.emit(debate_id, 'debate_failed', payload)
        finally:
            if runner is not None:
                try:
                    runner.close()
                except Exception as exc:
                    log.warning('debate %s cleanup failed (%s)', debate_id, type(exc).__name__)
                    if audit is not None:
                        try:
                            audit.cleanup_error(exc)
                        except OSError:
                            log.warning('debate %s cleanup audit persistence failed', debate_id)

    def detail(self, debate_id):
        row = self.store.get(debate_id)
        result = {'debate_id': row['id'], 'snapshot_id': row['snapshot_id'], 'status': row['status'], 'statements': []}
        for event in self.store.events(debate_id):
            if event['type'] == 'statement_accepted':
                result['statements'].append(json.loads(event['data']))
            elif event['type'] in ('debate_completed', 'debate_failed'):
                result.update(json.loads(event['data']))
                result['status'] = 'completed' if event['type'] == 'debate_completed' else 'failed'
        return result
