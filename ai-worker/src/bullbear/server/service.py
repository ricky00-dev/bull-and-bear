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
from .errors import ApiError
from .store import Store

log = logging.getLogger(__name__)


class LiveRunner:
    def __init__(self, settings):
        self.settings = settings
        self.clients = []
        self.audit = None
        self.background_context = None

    def usage(self):
        totals = {}
        for client in self.clients:
            for call in client.usage_payload()['calls']:
                model = call['model']
                totals.setdefault(model, {'model': model})
                for key, value in call.items():
                    if key != 'model':
                        totals[model][key] = totals[model].get(key, 0) + value
        return {'calls': list(totals.values())}

    def run(self, snapshot, debate_id, max_extra_rounds, emit):
        settings = self.settings
        models = self.audit.data['config']['selected_models'] if self.audit else selected_models(settings)

        def client(role):
            with self.audit.stage(f'{role}_client_initialization') if self.audit else nullcontext():
                llm = LLM(models[role])
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


class Service:
    def __init__(self, settings, market, *, runner_factory=None, max_running=2):
        self.settings, self.market = settings, market
        self.runner_factory = runner_factory or (lambda: LiveRunner(settings))
        self.max_running = max_running
        self.store = Store(settings.data_dir / 'http')
        self.pool = ThreadPoolExecutor(max_workers=max_running, thread_name_prefix='debate')

    def close(self):
        self.pool.shutdown(wait=True)
        self.store.close()

    def create(self, body):
        fingerprint = json.dumps({'ticker': body.ticker, 'max_extra_rounds': body.max_extra_rounds}, sort_keys=True)
        existing = self.store.request(body.request_id, fingerprint)
        if existing:
            return self.response(existing, True)
        quote = self.market.quote(body.ticker)
        if quote.reasons:
            raise ApiError(422, 'NOT_ELIGIBLE', '토론할 수 없는 종목입니다', reasons=quote.reasons)
        row, reused = self.store.create(body.request_id, fingerprint, body.ticker,
                                        quote.bars[-1].date.isoformat(), self.max_running)
        if not reused:
            try:
                self.pool.submit(self.run, row['id'], quote, body.max_extra_rounds)
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

    def run(self, debate_id, quote, max_extra_rounds):
        runner = None
        audit = None

        def collect_usage():
            try:
                if audit is not None and (not audit.data['usage_complete'] or any(
                    call['status'] in ('running', 'failure')
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
            audit = RunAudit(self.settings.data_dir, debate_id, ticker=quote.ticker,
                             data_date=quote.bars[-1].date.isoformat(),
                             max_extra_rounds=max_extra_rounds, models=selected_models(self.settings),
                             efforts={'debater': self.settings.debater_effort,
                                      'moderator': self.settings.moderator_effort},
                             secrets=(self.settings.dart_api_key, self.settings.krx_api_key,
                                      self.settings.naver_client_id, self.settings.naver_client_secret))
            with audit.stage('snapshot'):
                snapshot = self.market.snapshot(quote)
                audit.attach_snapshot(snapshot)
                self.store.save_snapshot(debate_id, snapshot)
            self.store.emit(debate_id, 'snapshot_created', dict(snapshot_id=snapshot.snapshot_id,
                            ticker=snapshot.ticker, name=snapshot.name, as_of=snapshot.as_of,
                            close=snapshot.facts['PX.CLOSE'].value, warnings=snapshot.warnings))
            background_context = None
            retrieval_config = {'enabled': self.settings.rag_enabled,
                                'generation_id': self.settings.rag_generation_id,
                                'profile': self.settings.rag_profile}
            if self.settings.rag_enabled:
                with audit.stage('knowledge_context'):
                    if not self.settings.rag_generation_id:
                        raise ValueError('RAG requires an explicit ready generation')
                    if self.settings.rag_profile != 'knowledge-short-v1':
                        raise ValueError('unsupported RAG profile')
                    from ..rag.retrieval import Retriever
                    from ..rag.store import RagStore
                    with RagStore(self.settings.data_dir / 'rag') as rag_store:
                        background_context = Retriever(rag_store).retrieve(
                            snapshot, generation_id=self.settings.rag_generation_id)
            policy = execution_policy(background_context)
            retrieval_config['execution'] = policy
            # Keep the failed/empty retrieval evidence even when no background is
            # passed to the model. Persistence failure must prevent paid calls.
            audit.attach_context(background_context, retrieval_config=retrieval_config)
            if policy['action'] == 'abort':
                raise RuntimeError('knowledge retrieval did not complete')
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

            with audit.stage('debate'):
                completed = runner.run(snapshot, debate_id, max_extra_rounds, emit)
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
