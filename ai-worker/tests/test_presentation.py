import json
import math
import statistics
from datetime import timedelta

import pytest

from bullbear import prompts
from bullbear.llm import LLMError
from bullbear.presentation import sentence_count, money_issues, statement_issues, moderator_issues, used_sources
from bullbear.schemas import Side
from bullbear.snapshot import build_snapshot, price_facts
from bullbear.tools import SnapshotTools
from .fakes import FakeSource, NOW, statement, ScriptedModerator


@pytest.fixture
def snap():
    return build_snapshot(FakeSource(), "000000", "가짜전자", now=NOW)


def codes(issues):
    return {i.code for i in issues}


def verdict():
    d = ScriptedModerator([]).evaluate([], {}, extra_allowed=False)
    d.decisive_evidence = ["PX.CLOSE", "PX.RET_1M"]
    d.reasoning = "7거래일 뒤 코스피 대비 비슷하게 움직일 것으로 봅니다 [E1]. 상승과 하락 요인이 상쇄될 것으로 예상합니다 [E2]."
    d.bull.comment = "가격 근거는 관련이 있습니다 [E1]."
    d.bear.comment = "하락 위험도 살폈습니다 [E2]."
    return d


def test_mkt_decisive_id_is_allowed_when_prose_uses_numbered_reference():
    d = verdict()
    d.decisive_evidence[0] = 'MKT.KOSPI_RET_7D'
    assert not moderator_issues(d)


@pytest.mark.parametrize('claim,too_long', [
    ('관측된 흐름의 지속은 불확실합니다.', False),
    ('최근 수익률은 1.57%입니다. 같은 흐름이 이어진다는 조건이 필요합니다.', False),
    ('최근 흐름이 약했습니다. 지속 여부는 불확실합니다. 새 자료가 필요합니다.', True),
])
def test_summary_accepts_two_sentences_without_splitting_decimals(claim, too_long):
    candidate = statement(('E1', 'PX.CLOSE', 399))
    candidate.claim = claim
    assert ('claim_length' in codes(statement_issues(candidate, 'opening', set()))) is too_long


def test_limits_and_decimal_citations():
    assert sentence_count("변동성은 68.17%입니다. [E1] 비율은 9.39배입니다 [E2]. 세 번째입니다.") == 3
    s = statement(('E1','PX.CLOSE',399), argument='하나. 둘. 셋. 넷.')
    assert 'argument_length' in codes(statement_issues(s,'opening',set()))
    s.claim = "첫 줄\n둘째 줄"
    assert 'claim_length' in codes(statement_issues(s,'opening',set()))
    s.evidence *= 4
    assert 'evidence_limit' in codes(statement_issues(s,'opening',set()))


@pytest.mark.parametrize('round_kind',['rebuttal','closing'])
def test_reusing_evidence_is_allowed_for_both_sides(snap,round_kind):
    old = statement(('E1','PX.CLOSE',399))
    history = [prompts.render_statement(Side.BEAR,'opening',old)]
    used = used_sources(history,snap)
    assert used == {'PX.CLOSE'}
    assert 'no_new_evidence' not in codes(statement_issues(old,round_kind,used))
    fresh = statement(('E1','PX.RET_1M',2))
    assert 'no_new_evidence' not in codes(statement_issues(fresh,round_kind,used))




def test_rebuttal_requires_actual_opponent_quote():
    from bullbear.presentation import rebuttal_target_issues
    own = statement(('E1', 'PX.CLOSE', 399), argument='단일일 반등과 공시를 봤습니다.')
    other = statement(('E1', 'PX.CLOSE', 399), argument='최근 가격 약세가 누적되었습니다.')
    history = [prompts.render_statement(Side.BULL, 'opening', own),
               prompts.render_statement(Side.BEAR, 'opening', other)]
    missed = statement(('E1', 'PX.CLOSE', 399), argument='상대의 주장은 단일일 반등 관찰과 공시 존재만으로 초과수익을 확신하는 점이 약합니다.')
    assert 'rebuttal_target' in codes(rebuttal_target_issues(missed, Side.BULL, 'rebuttal', history))
    missed.argument = '상대의 “단일일 반등과 공시”는 근거가 부족합니다.'
    assert rebuttal_target_issues(missed, Side.BULL, 'rebuttal', history)
    missed.argument = '상대의 “최근 가격 약세가 누적”된 점만으로 향후 하락을 단정할 수 없습니다.'
    assert not rebuttal_target_issues(missed, Side.BULL, 'rebuttal', history)
    missed.argument = '“최근 가격 약세가 누적”되었다는 상대 말만으로 향후 하락을 단정할 수 없습니다.'
    assert not rebuttal_target_issues(missed, Side.BULL, 'rebuttal', history)
    assert not rebuttal_target_issues(own, Side.BULL, 'opening', [])


@pytest.mark.parametrize('text,bad',[
    ('영업이익 178,964,931,000,000원',True),
    ('영업이익 1467252.09억 원',True),
    ('약 178.96조 원',False),
    ('주가 242,000원',False),
])
def test_large_money(text,bad):
    assert bool(money_issues(text)) is bad


def test_tool_display_does_not_change_raw_amount(snap):
    f=snap.facts['FIN.2026H1.OPERATING_INCOME_YTD']
    snap.facts[f.id]=f.model_copy(update={'value':178964931000000.0})
    item=next(v for v in json.loads(SnapshotTools(snap)('get_financials',{}))['items'] if v['id']==f.id)
    assert item['display']=='약 178.96조 원'
    assert item['value']==178964931000000.0


def test_moderator_refs_are_local_to_decisive_list():
    d=verdict()
    assert not moderator_issues(d)
    d.reasoning += ' 다른 근거 [E3].'
    assert 'verdict_refs' in codes(moderator_issues(d))
    d=verdict();d.decisive_evidence=['PX.CLOSE','PX.CLOSE']
    assert 'verdict_refs' in codes(moderator_issues(d))


@pytest.mark.parametrize('text,code',[
    ('PX.CLOSE가 높습니다.','internal_details'),
    ('MKT.KOSPI_RET_7D를 확인했습니다 [E1].','internal_details'),
    ('반려 횟수는 4회입니다.','internal_details'),
    ('evidence_accuracy는 1.0입니다.','internal_details'),
    ('장기 투자자는 분할매수하세요.','investor_advice'),
])
def test_moderator_hides_internal_detail_and_advice(text,code):
    d=verdict();d.bull.comment=text
    assert code in codes(moderator_issues(d))


def test_hold_does_not_require_a_benchmark_return_interval():
    d=verdict();d.reasoning='자료만으로 상승 방향을 확신하기 어려워 판단을 보류합니다 [E1][E2].'
    assert not moderator_issues(d)


def test_volatility_is_annualized_sample_sd():
    bars=FakeSource().get_daily_prices('000000',NOW.date()-timedelta(days=60),NOW.date())[-21:]
    from dataclasses import replace
    bars=[replace(b, close=100*math.exp(.01*i+(.03 if i%2 else 0))) for i,b in enumerate(bars)]
    returns=[math.log(b.close/a.close) for a,b in zip(bars,bars[1:])]
    f=next(f for f in price_facts(bars) if f.id=='PX.VOL_20D')
    assert f.value==round(statistics.stdev(returns)*math.sqrt(252)*100,2)
    assert '연율화' in f.label and '표본표준편차' in f.note
