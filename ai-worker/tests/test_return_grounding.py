from datetime import date, datetime, timezone

import pytest

from bullbear.return_grounding import return_issues
from bullbear.snapshot import Fact, Snapshot


def snapshot(value=-0.84, days=21):
    key = f'PX.EXCESS_KOSPI_{days}D'
    return Snapshot(snapshot_id='guard-case', ticker='000000', name='test',
                    as_of=date(2026, 10, 30), created_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
                    provider='fixture', facts={key: Fact(id=key, category='price', label='relative',
                    value=value, unit='%', as_of=date(2026, 10, 30), source='derived')})


def codes(text, value=-0.84, days=21):
    return {i.code for i in return_issues(text, snapshot(value, days), {'E1': f'PX.EXCESS_KOSPI_{days}D'})}


@pytest.mark.parametrize('text,value', [
    ('최근 한 달 주가는 코스피보다 0.84%p 덜 떨어져 종목 고유의 약세는 뚜렷하지 않았고, 이 관측이 매수 판단의 출발점입니다 [E1].', -0.84),
    ('상대수익은 −0.84%p로 코스피보다 더 올랐습니다.', -0.84),
    ('코스피보다 0.84%p 더 하락했습니다 [E1].', 0.84),
])
def test_reject_reversed_sign_including_recorded_failure(text, value):
    assert 'relative_return_sign' in codes(text, value)


@pytest.mark.parametrize('text,value', [
    ('코스피보다 수익률이 0.84%p 낮았습니다 [E1].', -0.84),
    ('코스피보다 0.84%p 더 하락했습니다 [E1].', -0.84),
    ('코스피보다 0.84%p 덜 떨어졌습니다 [E1].', 0.84),
    ('상대수익 −0.84%p를 덜 떨어졌다고 해석하는 것은 잘못입니다.', -0.84),
    ('상대는 "코스피보다 덜 떨어졌다"고 했지만 자료를 재검토해야 합니다 [E1].', -0.84),
    ('앞으로 코스피보다 더 오를 수 있다는 가정입니다.', -0.84),
])
def test_do_not_reject_correct_sign_quotes_or_unreferenced_forecast(text, value):
    assert not codes(text, value)


def test_recorded_cross_sentence_historical_three_day_mix():
    text = ('최근 3거래일 약세는 −2.29%p라는 실제 관측입니다 [E1]. '
            '다만 이 판정은 7거래일 뒤의 결과로 정해지며, 3거래일 수치는 그 중간 관찰일 뿐입니다.')
    assert 'historical_forecast_mix' in codes(text, -2.29, 3)


@pytest.mark.parametrize('text', [
    '최근 3거래일 관측은 미래 구간의 중간 관찰입니다 [E1].',
    '이 값은 이미 진행된 평가 구간의 중간 결과입니다 [E1].',
])
def test_reject_historical_result_as_future_progress(text):
    assert 'historical_forecast_mix' in codes(text, -2.29, 3)


@pytest.mark.parametrize('text', [
    '최근 3거래일은 과거 관측이며 미래의 중간 관찰이 아닙니다 [E1].',
    '기준일 이후 3거래일 결과는 미래 전망의 중간 관찰입니다.',
    '과거 3거래일 상대수익을 참고하되 앞으로도 부진이 지속된다는 가정입니다 [E1].',
])
def test_allow_correct_time_and_conditional_forecast(text):
    assert not codes(text, -2.29, 3)


def test_calendar_week_mistranslation():
    assert 'trading_day_calendar_mix' in codes('최근 21거래일 관측은 과거 3주 동안의 약세입니다 [E1].')
    assert not codes('과거 21거래일 동안 코스피보다 부진했습니다 [E1].')


def test_citation_sentence_boundary_keeps_later_disclaimer_from_hiding_error():
    # Full v5 paragraph: a later '아닌' must not suppress the first sentence.
    text = ('최근 한 달 주가는 코스피보다 0.84%p 덜 떨어져 종목 고유의 약세는 뚜렷하지 않았고, '
            '이 관측이 매수 판단의 출발점입니다 [E1]. '
            'PER 8.73배는 현재 수준을 보여주지만 미래는 알려주지 않습니다 [E2]. '
            '이 판단은 강한 확신이 아닌 약한 매수 판단입니다 [E3].')
    assert 'relative_return_sign' in codes(text)


def test_signed_distance_is_not_repeated_with_lower_than():
    assert 'relative_return_signed_distance' in codes('코스피 수익률보다 각각 -2.29%p, -2.17%p 낮았습니다 [E1].')
    assert not codes('상대수익은 -0.84%p로, 코스피보다 수익률이 0.84%p 낮았습니다 [E1].')


def test_evidence_interpretation_reference_precedes_its_sentence():
    assert 'relative_return_sign' in codes('[E1] 종목이 코스피보다 0.84%p 덜 떨어졌습니다.')
