from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from fastapi.encoders import jsonable_encoder

from ..agents import Debater, Moderator
from ..data.base import DataUnavailable
from ..debate import Debate, verification_stats
from ..events import EventLog
from ..llm import LLM, LLMError
from .errors import ApiError
from .store import Store

log = logging.getLogger(__name__)


class LiveRunner:
    def __init__(self, settings):
        self.settings = settings
        self.clients = []

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
        debater_llm = LLM(os.getenv('BULLBEAR_DEBATER_MODEL', settings.model))
        self.clients.append(debater_llm)
        moderator_llm = LLM(os.getenv('BULLBEAR_MODERATOR_MODEL', settings.model))
        self.clients.append(moderator_llm)
        result = Debate(snapshot, Debater(debater_llm, snapshot, effort=settings.debater_effort),
                        Moderator(moderator_llm, snapshot, effort=settings.moderator_effort),
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
            self.pool.submit(self.run, row['id'], quote, body.max_extra_rounds)
        return self.response(row, reused)

    @staticmethod
    def response(row, reused):
        return {'debate_id': row['id'], 'snapshot_id': row['snapshot_id'], 'status': row['status'], 'reused': reused}

    def run(self, debate_id, quote, max_extra_rounds):
        runner = None
        try:
            snapshot = self.market.snapshot(quote)
            self.store.save_snapshot(debate_id, snapshot)
            self.store.emit(debate_id, 'snapshot_created', dict(snapshot_id=snapshot.snapshot_id,
                            ticker=snapshot.ticker, name=snapshot.name, as_of=snapshot.as_of,
                            close=snapshot.facts['PX.CLOSE'].value, warnings=snapshot.warnings))
            runner = self.runner_factory()

            def emit(event, payload):
                # Never forward raw tokens or private moderator/audit events.
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

            completed = runner.run(snapshot, debate_id, max_extra_rounds, emit)
            self.store.emit(debate_id, 'debate_completed', {**completed, 'usage': runner.usage()})
        except Exception as exc:
            # Provider exception strings may contain API keys. Keep public errors generic.
            code = 'DATA_UNAVAILABLE' if isinstance(exc, DataUnavailable) or runner is None else 'LLM_ERROR'
            log.warning('debate %s failed (%s)', debate_id, type(exc).__name__)
            payload = {'error': {'code': code, 'message': '데이터 조회에 실패했습니다' if code == 'DATA_UNAVAILABLE' else 'AI 토론을 완료하지 못했습니다'}}
            if runner is not None:
                payload['usage'] = runner.usage()
            self.store.emit(debate_id, 'debate_failed', payload)
        finally:
            if runner is not None:
                runner.close()

    def detail(self, debate_id):
        row = self.store.get(debate_id)
        result = {'debate_id': row['id'], 'snapshot_id': row['snapshot_id'], 'status': row['status'], 'statements': []}
        for event in self.store.events(debate_id):
            if event['type'] == 'statement_accepted':
                result['statements'].append(json.loads(event['data']))
            elif event['type'] in ('debate_completed', 'debate_failed'):
                result.update(json.loads(event['data']))
        return result
