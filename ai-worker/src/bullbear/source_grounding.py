"""Bounded publication-date and PER wording guards for frozen worker facts.

Relative calendar wording is an editorial precision rule, not proof of an
incorrect date. These guards do not authenticate articles or value stocks.
"""
import re
from datetime import date

from .snapshot import KST
from .verifier import Issue


def source_context(snapshot):
    news = []
    for fact in snapshot.facts.values():
        if fact.category != 'news':
            continue
        published = fact.published_at.astimezone(KST) if fact.published_at else None
        news.append({'source_id': fact.id,
                     'publication_date_kst': published.date().isoformat() if published else None,
                     'event_date': None,
                     'event_date_status': 'not_separately_structured_do_not_infer_from_publication',
                     'available_scope': 'title_and_summary' if fact.note else 'title'})
    per = snapshot.facts.get('VAL.PER_TTM')
    return {'price_date': str(snapshot.as_of), 'articles': news,
            'per': None if per is None else {
                'source_id': per.id, 'value': per.value, 'unit': per.unit,
                'as_of': str(per.as_of), 'calculation_note': per.note,
                'comparison_basis': 'no_structured_peer_or_historical_per_benchmark',
                'permitted_interpretation': '현재 이익 기준 가격 배수. 수치 자체는 싸거나 비싸다는 판단이 아님.',
            },
            'instructions': [
                '기사 인용 시 확인된 발행일을 절대 날짜로 쓰고, 사건 발생일은 인용한 본문 또는 요약에서 별도로 확인한 경우에만 말한다.',
                '오늘/어제/다음 날/발표 당일 같은 상대 날짜 대신 확인된 YYYY-MM-DD를 쓴다. 날짜가 없으면 미확인이라고 한다.',
                '현재 PER과 비교 대상의 회계기간·이익 정의가 맞는 별도 근거 없이는 낮음/쌈/저평가/가격 부담 작음을 주장하지 않는다.',
                '이 스냅샷 경로에는 검증된 업종/과거 PER 비교 필드가 없다. 알려진 기억이나 임의 임계값으로 채우지 않는다.',
            ]}


def source_issues(text, snapshot, references=None, *, news_results=None):
    references = references or {}
    news_results = news_results or {}
    issues = []
    for sentence in re.split(r'(?<!\d)\.(?!\d)\s*|\n+', text):
        # Inspect the author's assertions, not exact quotations being challenged.
        assertion = re.sub(r'[“「][^”」]*[”」]|"[^"]*"', '', sentence)
        cited = [snapshot.facts.get(references.get(ref, '')) for ref in re.findall(r'\[(E\d+)\]', sentence)]
        news = [f for f in cited if f is not None and f.category == 'news']
        body_claim = re.search(
            r'(?:기사\s*)?(?:본문|원문)\s*(?:에서\s*확인|에\s*따르면|을\s*(?:읽었|확인했))', assertion)
        qualified = re.search(r'미확인|못했|않았|않아|수\s*없|실패', assertion)
        if (len(news) == 1 and body_claim and not qualified
                and not news_results.get(news[0].id, {}).get('verified_full_text')):
            issues.append(Issue(severity='error', code='news_body_unverified',
                message=f'{news[0].id}: 기사 본문이 확인되지 않았습니다. 저장된 요약문 범위에서 인용하세요.'))
        relative = re.search(r'발표\s*(?:당일|다음\s*날|하루\s*(?:전|뒤|후))|기준일\s*(?:다음\s*날|하루\s*(?:전|뒤|후))|(?:오늘|어제)\s*(?:기사|보도)|(?:기사|보도)\s*(?:다음\s*날|당일)', assertion)
        correction = re.search(r'표현.{0,20}(?:틀|잘못|맞지|부정확)|설명.{0,15}맞지|(?:라고|이라는).{0,20}(?:잘못|틀|맞지)|쓰지\s*않', assertion)
        if relative and not correction:
            issues.append(Issue(severity='error', code='news_relative_date',
                message='기사/발표와 기준일을 상대 날짜로 연결하지 말고 확인된 발행일을 YYYY-MM-DD로 쓰세요. '
                        '발행일은 사건 발생일이 아닙니다. 사건 날짜가 없으면 발생일을 단정하지 마세요.'))
        # Date immediately qualifying publication, with one unambiguous source.
        if len(news) == 1 and news[0].published_at:
            actual = news[0].published_at.astimezone(KST).date()
            patterns = [r'(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?:에|자|\s)*(?:발행|보도|기사)',
                        r'(?:(?P<year>20\d{2})년\s*)?(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일(?:에|자|\s)*(?:발행|보도|기사)']
            for pattern in patterns:
                for match in re.finditer(pattern, assertion):
                    try:
                        stated = date(int(match['year'] or actual.year), int(match['month']), int(match['day']))
                    except ValueError:
                        stated = None
                    if stated != actual:
                        issues.append(Issue(severity='error', code='news_publication_date',
                            message=f'인용 기사 {news[0].id}의 확인된 발행일은 {actual.isoformat()}입니다. '
                                    '발행일과 기사 속 사건 날짜를 구분하세요.'))
        per_bound = bool(re.search(r'PER|주가수익비율', assertion, re.I)) or any(
            f is not None and f.id == 'VAL.PER_TTM' for f in cited)
        if per_bound:
            # Deliberately exclude generic "낮다고 반등을 보장하지 않는다".
            unsupported = re.search(
                r'(?:PER|주가수익비율).{0,65}(?:낮은\s*편|낮아서|낮아\s|낮고|낮으므로|낮다는\s*(?:점|관찰|계산|해석))'
                r'|이익.{0,18}(?:대비|비해).{0,25}(?:주가|가격).{0,15}(?:낮은|낮다는|낮아|낮고)'
                r'|(?:주가|가격)\s*부담.{0,15}(?:크지\s*않|작은|작아|낮은|높지\s*않)'
                r'|(?:저평가(?:되어|돼|된\s*상태|입니다)|저렴한\s*편|싼\s*편|싸다는\s*점|과도하게\s*눌렸)',
                assertion, re.I)
            if unsupported:
                issues.append(Issue(severity='error', code='per_without_comparison',
                    message='현재 PER 수치만으로 낮다/싸다/가격 부담이 작다고 평가했습니다. '
                            '이 자료에는 검증된 동종업체·과거 PER 비교 기준이 없습니다. '
                            'PER 값과 계산 기준만 설명하고 다른 실제 근거로 전망을 논증하세요. '
                            '반등을 보장하지 않는다는 단서를 붙여도 비교 근거 부재는 해결되지 않습니다.'))
    return issues
