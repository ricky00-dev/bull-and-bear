"""Bounded publication-date and PER wording guards for frozen worker facts.

Relative calendar wording is an editorial precision rule, not proof of an
incorrect date. These guards do not authenticate articles or value stocks.
"""
import re
from datetime import date

from .snapshot import KST
from .verifier import Issue


def source_issues(text, snapshot, references=None):
    references = references or {}
    issues = []
    for sentence in re.split(r'(?<!\d)\.(?!\d)\s*|\n+', text):
        # Inspect the author's assertions, not exact quotations being challenged.
        assertion = re.sub(r'[“「][^”」]*[”」]|"[^"]*"', '', sentence)
        cited = [snapshot.facts.get(references.get(ref, '')) for ref in re.findall(r'\[(E\d+)\]', sentence)]
        news = [f for f in cited if f is not None and f.category == 'news']
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
