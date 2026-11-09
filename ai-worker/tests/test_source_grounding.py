from datetime import date, datetime, timezone

import pytest

from bullbear.snapshot import Fact, Snapshot
from bullbear.source_grounding import source_context, source_issues


def snapshot():
    return Snapshot(snapshot_id='source-case', ticker='000000', name='test',
        as_of=date(2026, 10, 30), created_at=datetime(2026, 11, 2, 6, tzinfo=timezone.utc),
        provider='fixture', facts={
            'NEWS.A': Fact(id='NEWS.A', category='news', label='평가 기사', value=None,
                unit='text', as_of=date(2026, 11, 2), source='fixture',
                published_at=datetime(2026, 11, 1, 16, tzinfo=timezone.utc)),
            'VAL.PER_TTM': Fact(id='VAL.PER_TTM', category='valuation', label='PER',
                value=8.46, unit='x', as_of=date(2026, 10, 30), source='derived',
                note='시가총액 / 최근 4분기 순이익'),
        })


REFS = {'E1': 'NEWS.A', 'E2': 'VAL.PER_TTM'}


def codes(text):
    return {i.code for i in source_issues(text, snapshot(), REFS)}


def test_publication_kst_is_not_event_date_or_price_date():
    context = source_context(snapshot())
    assert context['price_date'] == '2026-10-30'
    assert context['articles'][0]['publication_date_kst'] == '2026-11-02'
    assert context['articles'][0]['event_date'] is None
    assert context['per']['value'] == 8.46
    assert context['per']['comparison_basis'].startswith('no_structured')


@pytest.mark.parametrize('text', [
    '발표 다음 날 장중 주가가 급락했다는 기사가 있습니다 [E1].',
    '기준일 다음 날 증권가 기사에서 평가가 나왔습니다 [E1].',
    '발표 당일에는 주가가 하락했습니다 [E1].',
])
def test_relative_publication_event_wording_is_requested_as_absolute(text):
    assert 'news_relative_date' in codes(text)


@pytest.mark.parametrize('text', [
    '2026-10-31 발행 기사에 따르면 환원 정책이 기대에 못 미쳤습니다 [E1].',
    '10월 31일 기사에 따르면 평가가 나왔습니다 [E1].',
])
def test_wrong_explicit_publication_date(text):
    assert 'news_publication_date' in codes(text)


@pytest.mark.parametrize('text', [
    '2026-11-02 발행 기사 요약은 실망 평가를 전합니다 [E1].',
    '11월 2일 기사에 따르면 실망 평가가 있었습니다 [E1].',
    '2026-10-29 발생 사건을 2026-11-02 발행 기사에서 전했습니다 [E1].',
    '기준일 다음 날이라는 설명은 기사 날짜와 맞지 않습니다 [E1].',
    '상대는 “발표 다음 날”이라고 했지만 실제 날짜를 대조해야 합니다 [E1].',
    '기준일 이후 7거래일 종가를 예측합니다.',
])
def test_correct_dates_distinct_event_date_correction_and_forecast(text):
    assert not codes(text)


@pytest.mark.parametrize('text', [
    'PER 8.46배로 낮은 편이라 상대 반등의 여지가 있습니다 [E2].',
    'PER은 9.39배로 이익에 비해 주가가 낮은 편이지만, 반등을 보장하지는 않습니다 [E2].',
    '[E2] 이익 규모에 비해 주가 부담이 크지 않은 편입니다.',
    '[E2] 이익 대비 가격 부담이 작아 회복 가능성이 있습니다.',
    'PER 8.46배로 주가가 과도하게 눌렸다면 반등 여지가 있습니다 [E2].',
    'PER 8.46배로 낮은 편입니다 [E2]. 다만 반등을 보장하는 것은 아닙니다.',
])
def test_unbenchmarked_valuation_not_excused_by_disclaimer(text):
    assert 'per_without_comparison' in codes(text)


@pytest.mark.parametrize('text', [
    'PER은 8.46배이며 현재 이익 기준 가격 배수입니다 [E2].',
    'PER이 낮다고 반등을 보장하지는 않습니다 [E2].',
    '비교 자료가 없어 PER이 낮다고 단정하기 어렵습니다 [E2].',
    '상대의 “PER이 낮은 편”이라는 설명에는 비교 근거가 없습니다 [E2].',
    'PER은 시가총액을 최근 4분기 순이익으로 나눈 값입니다 [E2].',
])
def test_allow_definition_nonvaluation_and_challenge(text):
    assert not codes(text)


def test_disclaimer_in_later_sentence_does_not_hide_first_error():
    text = ('최근 4분기 기준 PER은 8.46배로 이익에 비해 주가가 낮은 편이고 [E2], '
            '실적 개선이 반등 여지를 줍니다. 다만 저PER이 반등을 보장하는 것은 아닙니다.')
    assert 'per_without_comparison' in codes(text)
