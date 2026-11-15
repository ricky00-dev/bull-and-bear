"""대형주 30종목: 검색 결과 위쪽 정렬과 CLI 기본 목록. 토론 허용 기준은 server.market.block_reasons (보통주 전체)."""

UNIVERSE: dict[str, str] = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스",
    "005380": "현대차",
    "000270": "기아",
    "068270": "셀트리온",
    "005490": "POSCO홀딩스",
    "035420": "NAVER",
    "035720": "카카오",
    "051910": "LG화학",
    "006400": "삼성SDI",
    "105560": "KB금융",
    "055550": "신한지주",
    "086790": "하나금융지주",
    "012330": "현대모비스",
    "028260": "삼성물산",
    "066570": "LG전자",
    "003550": "LG",
    "032830": "삼성생명",
    "015760": "한국전력",
    "017670": "SK텔레콤",
    "034730": "SK",
    "096770": "SK이노베이션",
    "012450": "한화에어로스페이스",
    "329180": "HD현대중공업",
    "009540": "HD한국조선해양",
    "018260": "삼성에스디에스",
    "011200": "HMM",
    "033780": "KT&G",
}


class UnknownTicker(LookupError):
    pass


def resolve(query: str) -> tuple[str, str]:
    """종목코드 또는 종목명으로 (코드, 이름)을 찾는다."""
    query = query.strip()
    if query in UNIVERSE:
        return query, UNIVERSE[query]
    for code, name in UNIVERSE.items():
        if name.lower() == query.lower():
            return code, name
    raise UnknownTicker(f"대상 종목이 아닙니다: {query} (bullbear universe로 목록 확인)")
