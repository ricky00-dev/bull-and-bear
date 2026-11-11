"""Narrow return-wording guards applied after generation."""
import re

from .verifier import Issue


def return_issues(text, snapshot, references=None):
    """Reject only localized, affirmative contradictions; quotes/corrections are skipped.

    A sentence must name a signed excess return or cite an unambiguous excess
    return Fact. Mixed-sign citations are not resolved heuristically.
    """
    references = references or {}
    issues = []
    normalized = text.replace('−', '-').replace('–', '-')
    historical_refs = any(references.get(ref, '').startswith('PX.EXCESS_KOSPI_')
                          for ref in re.findall(r'\[(E\d+)\]', normalized))
    for sentence in re.split(r'(?<!\d)\.(?!\d)\s*|\n+', normalized):
        if re.search(r'["“”‘’「」]|아니|아님|아닙|아닌|잘못|오류|틀렸|틀린|정정', sentence):
            continue
        cited = [snapshot.facts.get(references.get(ref, '')) for ref in re.findall(r'\[(E\d+)\]', sentence)]
        excess = [f for f in cited if f is not None and f.id.startswith('PX.EXCESS_KOSPI_') and f.value is not None]
        signs = {1 if f.value > 0 else -1 if f.value < 0 else 0 for f in excess}
        # Explicit signed percentages need local relative-return language.
        if re.search(r'상대수익|초과수익', sentence):
            signs.update(1 if float(v) > 0 else -1 if float(v) < 0 else 0
                         for v in re.findall(r'([+-]\d+(?:\.\d+)?)\s*%p', sentence))
        opposite = (signs == {-1} and re.search(r'코스피보다.{0,25}(?:덜\s*(?:떨어(?:졌|져|진)|하락(?:했|해))|더\s*(?:올랐|상승했)|높았|높은\s*수익)', sentence))
        opposite = opposite or (signs == {1} and re.search(r'코스피보다.{0,25}(?:더\s*(?:떨어(?:졌|져|진)|하락(?:했|해))|덜\s*(?:올랐|상승했)|낮았|낮은\s*수익)', sentence))
        if opposite:
            issues.append(Issue(severity='error', code='relative_return_sign',
                message='상대수익 부호를 반대로 해석했습니다. 음수는 코스피보다 부진, 양수는 우위입니다. '
                        '절대 등락이 없으면 더/덜 하락 대신 코스피보다 수익률이 낮다/높다로 표현하세요.'))
        if re.search(r'코스피(?:\s*수익률)?보다.{0,80}-\d+(?:\.\d+)?\s*%p.{0,30}(?:낮|높)', sentence):
            issues.append(Issue(severity='error', code='relative_return_signed_distance',
                message='음수와 낮다/높다를 겹쳐 쓰지 마세요. 상대수익 -2.29%p라면 '
                        '코스피보다 수익률이 2.29%p 낮았다처럼 차이는 양의 크기로 쓰세요.'))
        historical = bool(excess) or bool(re.search(r'(?:과거|최근)\s*(?:3|7|21)거래일', sentence))
        historical |= historical_refs and bool(re.search(r'3거래일\s*수치', sentence))
        if re.search(r'(?:기준일|T0)\s*이후\s*3거래일', sentence):
            historical = False
        if historical and re.search(r'중간\s*관찰|중간\s*결과|이미\s*진행된\s*(?:평가|예측)', sentence):
            issues.append(Issue(severity='error', code='historical_forecast_mix',
                message='기준일에 끝나는 과거 수익률은 기준일 이후 미래 구간의 중간 결과가 아닙니다. '
                        '두 구간을 분리하고 과거 관측으로 명시하세요.'))
        if (re.search(r'21거래일', sentence) or any(f.id.endswith('_21D') for f in excess)) and re.search(r'(?:과거|최근)\s*3주', sentence):
            issues.append(Issue(severity='error', code='trading_day_calendar_mix',
                message='21거래일은 3주가 아닙니다. 달력 주수로 바꾸지 말고 과거 21거래일로 쓰세요.'))
    return issues
