from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext

from fastapi.encoders import jsonable_encoder

from ..audit import AuditedLLM, RunAudit, selected_models
from ..data.base import DataUnavailable
from ..graph_runtime import MediationFailed, GraphRuntime, GraphStopped
from ..events import EventLog
from ..llm import LLM, validate_snapshot_model
from ..single import SingleAnalyst
from ..snapshot import Snapshot, HISTORICAL_DATA_POLICY
from .errors import ApiError
from .store import Store

log = logging.getLogger(__name__)


class LiveRunner:
    def __init__(self, settings, *, budget=None):
        self.settings = settings
        self.clients = []
        self.audit = None
        self.budget = budget
        self.budget_scopes = set()
        self.live_news = False

    def new_client(self, model, scope):
        validate_snapshot_model(model)
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

        def client(role, model_role):
            with self.audit.stage(f'{role}_client_initialization') if self.audit else nullcontext():
                llm = self.new_client(models[model_role], f'{debate_id}:{role}')
                self.clients.append(llm)
                return AuditedLLM(llm, self.audit, model_role) if self.audit else llm

        return GraphRuntime(snapshot, debate_id=debate_id,
            bull=client('bull', 'debater'), bear=client('bear', 'debater'),
            moderator=client('moderator', 'moderator'),
            log=EventLog(settings.debate_dir / f'{debate_id}.jsonl'), emit=emit,
            max_extra_rounds=max_extra_rounds, debater_effort=settings.debater_effort,
            moderator_effort=settings.moderator_effort,
            include_chart_image=self.budget is None,
            news_web_fetch=settings.news_web_fetch_enabled and self.live_news).run()

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
        verdict = SingleAnalyst(wrapped, snapshot, effort=self.settings.moderator_effort).evaluate(
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

    def close(self):
        self.pool.shutdown(wait=True)
        self.store.close()

    def create(self, body):
        identity = {'ticker': body.ticker, 'max_extra_rounds': body.max_extra_rounds}
        # Preserve fingerprints for pre-v0.6 and explicit default requests.
        if body.mode != 'debate' or body.snapshot_id is not None:
            identity.update(mode=body.mode, snapshot_id=body.snapshot_id)
        if body.as_of is not None:
            identity["as_of"] = body.as_of.isoformat()
        fingerprint = json.dumps(identity, sort_keys=True)
        existing = self.store.request(body.request_id, fingerprint)
        if existing:
            return self.response(existing, True)
        snapshot, quote = None, None
        if body.snapshot_id is not None:
            snapshot = Snapshot.model_validate(self.store.snapshot(body.snapshot_id))
            if snapshot.ticker != body.ticker:
                raise ApiError(400, 'INVALID_REQUEST', '스냅샷과 요청 종목이 다릅니다')
            if body.as_of is not None and (snapshot.as_of != body.as_of or snapshot.data_policy not in ("historical", HISTORICAL_DATA_POLICY)):
                raise ApiError(400, "INVALID_REQUEST", "스냅샷의 기준일 또는 데이터 정책이 요청과 다릅니다")
            data_date = snapshot.as_of.isoformat()
        else:
            quote = self.market.quote(body.ticker, as_of=body.as_of)
            if quote.reasons:
                raise ApiError(422, 'NOT_ELIGIBLE', '토론할 수 없는 종목입니다', reasons=quote.reasons)
            data_date = quote.bars[-1].date.isoformat()
        row, reused = self.store.create(body.request_id, fingerprint, body.ticker,
                                        data_date, self.max_running, mode=body.mode, snapshot_id=body.snapshot_id,
                                        data_policy=snapshot.data_policy if snapshot else (HISTORICAL_DATA_POLICY if body.as_of else "live"))
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
        from .progress import generation_progress
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
                                      self.settings.naver_client_id, self.settings.naver_client_secret,
                                      self.settings.fred_api_key, self.settings.ecos_api_key))
            with audit.stage('snapshot'):
                live_news = snapshot is None and quote.requested_as_of is None
                snapshot = snapshot if snapshot is not None else self.market.snapshot(quote)
                collected_at = snapshot.created_at
                self.store.save_snapshot(debate_id, snapshot)
                # A content-addressed ID may already exist with an earlier
                # observation cutoff. Both modes must use the stored object.
                snapshot = Snapshot.model_validate(self.store.snapshot(snapshot.snapshot_id))
                audit.attach_snapshot(snapshot)
            self.store.emit(debate_id, 'snapshot_created', dict(snapshot_id=snapshot.snapshot_id,
                            ticker=snapshot.ticker, name=snapshot.name, as_of=snapshot.as_of,
                            close=snapshot.facts['PX.CLOSE'].value, warnings=snapshot.warnings))
            with audit.stage('runner_initialization'):
                runner = self.runner_factory()
                if isinstance(runner, LiveRunner):
                    runner.audit = audit
                    runner.live_news = live_news and snapshot.created_at == collected_at
                audit.attach_runner(runner)

            def emit(event, payload):
                # Never forward raw tokens or private moderator/audit events.
                audit.observe_event(event, payload)
                if mode == 'single' and event != 'moderator_started':
                    return
                data = jsonable_encoder(payload)
                if event == 'statement_accepted':
                    verification = data.pop('verification', None) or {}
                    data['warnings'] = [i for i in verification.get('issues', []) if i['severity'] == 'warning']
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
                **completed, **({'usage': usage} if usage is not None else {}),
                'generation': generation_progress(self.store.events(debate_id), terminal='completed', mode=mode)})
        except Exception as exc:
            # Provider exception strings may contain API keys. Keep public errors generic.
            code = 'DATA_UNAVAILABLE' if isinstance(exc, DataUnavailable) or runner is None else 'LLM_ERROR'
            log.warning('debate %s failed (%s)', debate_id, type(exc).__name__)
            payload = {'error': {'code': code, 'message': '데이터 조회에 실패했습니다' if code == 'DATA_UNAVAILABLE' else 'AI 토론을 완료하지 못했습니다'}}
            payload['generation'] = generation_progress(self.store.events(debate_id), terminal='failed', mode=mode)
            payload['error']['stage'] = payload['generation']['stage']
            payload['error']['reason'] = ('moderator_validation_failed'
                if isinstance(exc, MediationFailed) else 'generation_failed')
            if isinstance(exc, GraphStopped):
                payload['error']['reason'] = 'graph_' + exc.graph_status
                payload['graph_status'] = exc.graph_status
                payload['generation']['moderator_status'] = exc.graph_status
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
        from .progress import generation_progress
        row = self.store.get(debate_id)
        result = {'debate_id': row['id'], 'snapshot_id': row['snapshot_id'], 'status': row['status'], 'statements': []}
        events = self.store.events(debate_id)
        for event in events:
            if event['type'] == 'statement_accepted':
                result['statements'].append(json.loads(event['data']))
            elif event['type'] in ('debate_completed', 'debate_failed'):
                result.update(json.loads(event['data']))
                result['status'] = 'completed' if event['type'] == 'debate_completed' else 'failed'
        result['generation'] = generation_progress(events, mode=row['mode'])
        return result
