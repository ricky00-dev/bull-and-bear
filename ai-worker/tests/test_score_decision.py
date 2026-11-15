import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from bullbear.events import EventLog
from bullbear.graph_runtime import MediationFailed, mean_score_decision, SCORE_FIELDS
from .graph_fakes import GraphLLM
from .test_graph_runtime import snapshot, runtime


@pytest.mark.parametrize('gap,expected', [(-.201, 'SELL'), (-.2, 'HOLD'),
    (0, 'HOLD'), (.2, 'HOLD'), (.201, 'BUY')])
def test_inclusive_hold_boundary(gap, expected):
    # Synthetic fractional scores exercise the exact boundary; production scores are integers.
    forecast = SimpleNamespace(bull=SimpleNamespace(**dict.fromkeys(SCORE_FIELDS, gap)),
                               bear=SimpleNamespace(**dict.fromkeys(SCORE_FIELDS, 0)))
    assert mean_score_decision(forecast)[0].value == expected


@pytest.mark.parametrize('original,delta,expected,calls', [
    ('HOLD', 0, 'HOLD', 1), ('BUY', 1, 'BUY', 1), ('SELL', -1, 'SELL', 1),
    ('HOLD', 1, 'BUY', 2), ('HOLD', -1, 'SELL', 2),
    ('BUY', 0, 'BUY', 1), ('SELL', 0, 'SELL', 1),
    ('BUY', -1, 'BUY', 1), ('SELL', 1, 'SELL', 1)])
def test_only_original_hold_is_calculated(snapshot, tmp_path, monkeypatch, original, delta, expected, calls):
    if original != 'HOLD':
        def unexpected_calculation(_):
            pytest.fail('BUY/SELL must not calculate a score decision')
        monkeypatch.setattr('bullbear.graph_runtime.mean_score_decision', unexpected_calculation)
    class Moderator(GraphLLM):
        def structured(self, conv, **kwargs):
            if self.count == 0:
                self.initial_conv = conv
                self.initial_messages = deepcopy(conv.messages)
                self.initial_schema = kwargs['schema']
            else:
                assert conv is not self.initial_conv
                assert len(conv.messages) == len(self.initial_messages)
                assert conv.messages[0] == self.initial_messages[0]
                assert conv.messages[2:] == self.initial_messages[2:]
                assert conv.context_ids is self.initial_conv.context_ids
                assert kwargs['schema'] == self.initial_schema
                payload = json.loads(conv.messages[1]['content'])
                original_payload = json.loads(self.initial_messages[1]['content'])
                assert f'forecast.decision={expected}' in payload['task']
                for key in original_payload.keys() - {'task'}:
                    assert payload[key] == original_payload[key]
                assert payload['fixed_scores'] == [3 + delta, 3, 3, 3, 3, 3, 3, 3]
            raw = deepcopy(super().structured(conv, **kwargs))
            raw['forecast']['bull'] = dict(raw['forecast']['bull'])
            raw['forecast']['bull']['relevance'] += delta
            raw['forecast']['decision'] = original if self.count == 1 else expected
            raw['forecast']['reasoning'] = f'해설 {self.count} [E1].'
            # Real clients append responses/tool history; regeneration must not inherit it.
            conv.messages.append({'role': 'assistant', 'content': json.dumps(raw)})
            return raw

    moderator = Moderator(snapshot)
    run = runtime(snapshot, tmp_path, moderator=moderator)
    verdict = run.run()['verdict']
    comparison = verdict['decision_comparison']
    assert verdict['decision'] == expected
    assert verdict['reasoning'] == f'해설 {calls} [E1].'
    assert moderator.count == calls
    assert comparison['original_verdict']['decision'] == original
    assert comparison['original_verdict']['reasoning'] == '해설 1 [E1].'
    assert comparison['original_verdict']['scores'] == verdict['scores']
    assert comparison['mean_gap'] == (delta / 4 if original == 'HOLD' else None)
    assert comparison['mean_decision'] == (expected if original == 'HOLD' else None)
    assert comparison['explanation_regenerated'] == (calls == 2)
    assert sum(e['type'] == 'moderator_original' for e in EventLog.read(run.log.path)) == 1


@pytest.mark.parametrize('invalid', ['decision', 'score', 'comment'])
def test_regeneration_failure_keeps_original_and_does_not_publish(snapshot, tmp_path, invalid):
    class Moderator(GraphLLM):
        def structured(self, conv, **kwargs):
            raw = deepcopy(super().structured(conv, **kwargs))
            raw['forecast']['bull'] = dict(raw['forecast']['bull'])
            raw['forecast']['bull']['relevance'] = 4
            if self.count > 1:
                raw['forecast']['decision'] = 'HOLD' if invalid == 'decision' else 'BUY'
                if invalid == 'score':
                    raw['forecast']['bull']['relevance'] = 5
                if invalid == 'comment':
                    raw['forecast']['bull']['comment'] = '변경된 평가'
            return raw

    run = runtime(snapshot, tmp_path, moderator=Moderator(snapshot))
    with pytest.raises(MediationFailed):
        run.run()
    assert run.moderator.count == 4
    events = EventLog.read(run.log.path)
    original = next(e for e in events if e['type'] == 'moderator_original')
    assert original['original_verdict']['decision'] == 'HOLD'
    assert not any(e['type'] == 'graph_mediated' for e in events)
