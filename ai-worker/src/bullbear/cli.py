"""명령줄 진입점.

  bullbear universe             대상 종목 목록
  bullbear snapshot 삼성전자     스냅샷만 만들어 출력 (LLM 호출 없음, 데이터 검증용)
  bullbear debate 005930        토론 → 사용자 판정 → 중재자 판정 공개
  bullbear replay <debate_id>   이벤트 기록 재생
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from .config import Settings, load_settings
from .data import DataUnavailable
from .data.naver_news import NaverNewsSource
from .data.pykrx_dart import PykrxDartSource
from .data.universe import UNIVERSE, UnknownTicker, resolve
from .events import EventLog
from .schemas import ROUND_LABELS, Decision, Side
from .snapshot import Snapshot, build_snapshot

_UNIT = {"KRW": "원", "KRW/share": "원", "%": "%", "x": "배", "shares": "주", "count": "", "text": ""}


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "-"
    if unit in ("%", "x"):
        return f"{value:,.2f}{_UNIT[unit]}"
    if unit == "KRW" and abs(value) >= 1e8:
        return f"{value / 1e8:,.0f}억원"
    return f"{value:,.0f}{_UNIT[unit]}"


def _make_snapshot(settings: Settings, query: str) -> Snapshot:
    ticker, name = resolve(query)
    source = PykrxDartSource(settings.dart_api_key, settings.cache_dir)
    try:
        news = NaverNewsSource(settings.naver_client_id, settings.naver_client_secret)
    except DataUnavailable as e:
        print(f"경고: {e}", file=sys.stderr)
        news = None
    snap = build_snapshot(source, ticker, name, news=news)
    snap.save(settings.snapshot_dir)
    return snap


def cmd_universe(_args, _settings: Settings) -> None:
    for code, name in UNIVERSE.items():
        print(f"{code}  {name}")


def cmd_snapshot(args, settings: Settings) -> None:
    snap = _make_snapshot(settings, args.ticker)
    print(f"{snap.name}({snap.ticker})  스냅샷 {snap.snapshot_id}  기준일 {snap.as_of}  공급자 {snap.provider}")
    for category in ("price", "financials", "valuation", "disclosure", "news"):
        facts = snap.by_category(category)
        print(f"\n[{category}] {len(facts)}개")
        for f in facts:
            if category == "news":
                print(f"  {f.id:<28} {f.published_at:%m-%d %H:%M}  {f.label}")
            elif f.unit == "text":
                print(f"  {f.id:<28} {f.as_of}  {f.label}" + (f"  ({f.note})" if f.note and category != "disclosure" else ""))
            else:
                print(f"  {f.id:<28} {f.label:<28} {_fmt(f.value, f.unit):>16}")
    for w in snap.warnings:
        print(f"\n경고: {w}")


def _printer(event: str, payload: dict) -> None:
    side = payload.get("side")
    if event == "turn_started":
        print(f"\n── {ROUND_LABELS[payload['round']]} · {side.label} 측 ", end="", flush=True)
    elif event == "tool_call":
        print(".", end="", flush=True)
    elif event == "statement_accepted":
        st, ver = payload["statement"], payload["verification"]
        mark = "검증 통과" if payload["verified"] else "검증 실패"
        print(f"({mark}, 시도 {payload['attempts']}회)")
        print(f"주장: {st.claim}\n{st.argument}")
        for e in st.evidence:
            print(f"  {e.ref} {e.source_id} = {e.value}  — {e.interpretation}")
        for i in ver.issues:
            print(f"  ! {i.severity}: {i.message}")
    elif event == "moderator_started":
        print("\n── 중재자 평가 중...", flush=True)
    elif event == "extra_round_requested":
        print(f"\n── 중재자가 추가 질문 라운드를 요청했습니다: {payload['question']}")


def _ask_user() -> tuple[Decision, str]:
    choices = {"1": Decision.BUY, "2": Decision.HOLD, "3": Decision.SELL, "buy": Decision.BUY,
               "hold": Decision.HOLD, "sell": Decision.SELL, "매수": Decision.BUY, "보류": Decision.HOLD, "매도": Decision.SELL}
    while True:
        raw = input("\n당신의 판정은? [1] 매수 [2] 보류 [3] 매도: ").strip().lower()
        if raw in choices:
            break
    reason = input("이유 한 줄: ").strip()
    return choices[raw], reason


def cmd_debate(args, settings: Settings) -> None:
    from .agents import Debater, Moderator  # anthropic 클라이언트는 토론할 때만 만든다
    from .debate import Debate, verification_stats
    from .llm import LLM

    snap = Snapshot.load(settings.snapshot_dir, args.snapshot) if args.snapshot else _make_snapshot(settings, args.ticker)
    for w in snap.warnings:
        print(f"경고: {w}")
    debate_id = f"{datetime.now():%Y%m%d-%H%M%S}-{snap.ticker}"
    print(f"{snap.name}({snap.ticker}) 토론 {debate_id}  스냅샷 {snap.snapshot_id}  기준일 {snap.as_of}")

    llm = LLM(settings.model)
    debate = Debate(
        snap,
        Debater(llm, snap, effort=settings.debater_effort),
        Moderator(llm, snap, effort=settings.moderator_effort),
        EventLog(settings.debate_dir / f"{debate_id}.jsonl"),
        debate_id=debate_id,
        max_extra_rounds=args.max_extra_rounds,
        on_event=_printer,
    )
    result = debate.run()

    if args.no_judge:
        user, reason = None, ""
    else:
        user, reason = _ask_user()
        debate.submit_user_verdict(user, reason)

    v = result.verdict
    print(f"\n══ 중재자 판정: {v.decision.label} (확신도 {v.confidence:.0%})")
    if user:
        print(f"   당신의 판정: {user.label} → {'일치' if user is v.decision else '불일치'}")
    print(f"\n{v.reasoning}")
    for side in (Side.BULL, Side.BEAR):
        s = getattr(v, side.value)
        print(f"  {side.label} 측  관련성 {s.relevance} 중요도 {s.materiality} 반박 {s.rebuttal} 리스크 {s.risk_awareness}  {s.comment}")
    print(f"  결정적 근거: {', '.join(v.decisive_evidence)}")
    print(f"\n검증 통계: {verification_stats(result.turns)}")
    u = llm.usage
    print(f"토큰: 입력 {u.input_tokens:,} / 출력 {u.output_tokens:,} / 캐시 읽기 {u.cache_read_input_tokens:,} ({u.requests}회 호출)")
    print(f"기록: {debate.log.path}")


def cmd_replay(args, settings: Settings) -> None:
    path = settings.debate_dir / f"{args.debate_id}.jsonl"
    for ev in EventLog.read(path):
        t = ev["type"]
        if t == "statement_attempt":
            ok = "통과" if ev["verification"]["passed"] else "반려"
            print(f"#{ev['seq']} [{ROUND_LABELS[ev['round']]}] {Side(ev['side']).label} 시도{ev['attempt']} {ok}: {ev['statement']['claim']}")
            for i in ev["verification"]["issues"]:
                print(f"      {i['severity']}: {i['message']}")
        elif t == "moderator_evaluated":
            d = ev["decision"]
            print(f"#{ev['seq']} 중재자 {d['action']} → {d['decision']} ({d['confidence']:.0%}) {d.get('extra_question') or ''}")
        else:
            rest = {k: v for k, v in ev.items() if k not in ("seq", "ts", "type", "statement", "verification")}
            print(f"#{ev['seq']} {t} {rest}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bullbear")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("universe")
    p = sub.add_parser("snapshot")
    p.add_argument("ticker")
    p = sub.add_parser("debate")
    p.add_argument("ticker")
    p.add_argument("--snapshot", help="기존 스냅샷 ID로 토론 (같은 시점 데이터로 재실험)")
    p.add_argument("--no-judge", action="store_true", help="사용자 판정 입력 생략")
    p.add_argument("--max-extra-rounds", type=int, default=1)
    p = sub.add_parser("replay")
    p.add_argument("debate_id")
    args = parser.parse_args(argv)

    settings = load_settings()
    handler = {"universe": cmd_universe, "snapshot": cmd_snapshot, "debate": cmd_debate, "replay": cmd_replay}[args.command]
    try:
        handler(args, settings)
    except (UnknownTicker, DataUnavailable) as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
