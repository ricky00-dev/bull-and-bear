"""CSV tables and metadata for model inputs from the frozen snapshot."""
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, time
from itertools import groupby
import json

from .chart_data import csv_rows
from .history import history_entry
from .snapshot import DAILY_FACT_PREFIX, Fact, Snapshot, chart_window_start, week_start

# Where the price stands and how it got there; the recent daily facts are added
# separately. Every one of these is citable as evidence without a lookup.
PRICE_IDS = (
    "PX.CLOSE", "PX.VOL_20D", "PX.MA200", "PX.VS_MA20", "PX.VS_MA60", "PX.VS_MA200",
    "PX.RET_1M", "PX.RET_3M", "PX.RET_1Y", "PX.FROM_HIGH_52W", "PX.FROM_LOW_52W", "PX.VOLUME_RATIO",
    "MKT.KOSPI_CLOSE", "MKT.KOSPI_VOL_20D",
    "MKT.KOSPI_RET_3D", "PX.EXCESS_KOSPI_3D",
    "MKT.KOSPI_RET_7D", "PX.EXCESS_KOSPI_7D",
    "MKT.KOSPI_RET_21D", "PX.EXCESS_KOSPI_21D",
)
VALUATION_IDS = ("VAL.PER_TTM", "VAL.PBR", "VAL.DEBT_RATIO")
NEWS_PREVIEW_TARGETS = {"market": 3, "company": 7}
_CORE_ACCOUNTS = {
    "REVENUE", "REVENUE_YTD", "REVENUE_YOY",
    "OPERATING_INCOME", "OPERATING_INCOME_YTD", "OPERATING_INCOME_YOY", "OPERATING_CASH_FLOW",
}


def expand_fact_ids(snapshot: Snapshot, ids: Iterable[str]) -> tuple[list[Fact], list[str]]:
    """Resolve cited/calculated facts without hiding missing dependency IDs."""
    pending, visited, missing = list(ids), set(), set()
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        fact = snapshot.facts.get(key)
        if fact is None:
            missing.add(key)
        else:
            pending.extend(fact.inputs)
    return [snapshot.facts[key] for key in sorted(visited - missing)], sorted(missing)


def core_fact_ids(snapshot: Snapshot) -> set[str]:
    """Fixed, side-neutral coverage of price, earnings, valuation and macro risk."""
    facts = snapshot.facts
    ids = {key for key in (*PRICE_IDS, *VALUATION_IDS) if key in facts}
    ids.update(key for key in facts if key.startswith(DAILY_FACT_PREFIX))
    # Keep the stock return as a fallback when the short-window comparison is missing.
    ids.update(f"PX.RET_{n}D" for n in (3, 7)
               if f"PX.EXCESS_KOSPI_{n}D" not in facts and f"PX.RET_{n}D" in facts)
    financials = snapshot.by_category("financials")
    latest = max((f for f in financials if f.source != "derived"),
                 key=lambda f: (f.as_of, f.report_period or "", f.id), default=None)
    if latest is not None:
        ids.update(f.id for f in financials if f.as_of == latest.as_of
                   and f.report_period == latest.report_period and f.report_basis == latest.report_basis
                   and (f.source == latest.source or f.source == "derived")
                   and f.id.rsplit(".", 1)[-1] in _CORE_ACCOUNTS)
    ids.update(f.id for f in snapshot.by_category("macro"))
    return ids


def ordered_news(snapshot: Snapshot, scope: str) -> list[Fact]:
    """Newest first; deterministic ties. No positive/negative sentiment selection."""
    def sort_key(fact):
        observed = fact.published_at or fact.available_at
        if observed is None:
            observed = datetime.combine(fact.as_of, time.min, snapshot.information_cutoff.tzinfo)
        elif observed.tzinfo is None:
            observed = observed.replace(tzinfo=snapshot.information_cutoff.tzinfo)
        return observed.timestamp(), fact.id

    return sorted((f for f in snapshot.by_category("news") if (f.news_scope or "company") == scope),
                  key=sort_key, reverse=True)


def _take_news(facts: list[Fact], limit: int, events: set[str]) -> list[Fact]:
    selected = []
    for fact in facts:
        if len(selected) == limit:
            break
        event = fact.event_id or fact.id
        if event not in events:
            selected.append(fact)
            events.add(event)
    return selected


def fact_for_model(fact: Fact, *, exclude_none: bool = False) -> dict:
    data = fact.model_dump(mode="json", exclude_none=exclude_none)
    if fact.category == "news":
        data.pop("url", None)
        if fact.source.startswith(("https://", "http://")) or fact.source == fact.url:
            data["source"] = fact.publisher or "news"
    return data


def _record_table(rows, base_columns) -> str:
    columns = dict.fromkeys(base_columns)
    for row in rows:
        for key, value in row.items():
            if value is not None and value != "":
                columns.setdefault(key)
    # Include CR in the CSV dialect so text containing a standalone CR is quoted.
    return csv_rows(columns, ((row.get(key) for key in columns) for row in rows), line_ending="\r\n")


def fact_table_csv(facts: Iterable[Fact]) -> str:
    rows = []
    for fact in sorted(facts, key=lambda item: item.id):
        row = fact_for_model(fact, exclude_none=True)
        row["source_id"] = row.pop("id")
        row.pop("url", None)  # The worker resolves links from source IDs.
        inputs = row.pop("inputs")
        if inputs:
            row["inputs"] = json.dumps(inputs, ensure_ascii=False, separators=(",", ":"))
        if fact.category == "news":
            if row.get("publisher") == row.get("source"):
                row.pop("publisher", None)
            if row.get("available_at") == row.get("published_at"):
                row.pop("available_at", None)
        rows.append(row)
    return _record_table(rows, ("source_id", "category", "label", "value", "unit", "as_of", "source"))


def _compact_fact_rows(rows):
    columns = ("source_id", "label", "value", "unit", "meta")
    table = _record_table(rows, columns)
    counts = Counter(row["note"] for row in rows if "note" in row)
    repeated = (note for note, count in counts.items() if count > 1)
    refs = {note: f"n{index}" for index, note in enumerate(repeated)}
    if not refs:
        return table, {}

    referenced_rows = [row.copy() for row in rows]
    for row in referenced_rows:
        if ref := refs.get(row.get("note")):
            row["note_ref"] = ref
            del row["note"]
    compact = _record_table(referenced_rows, columns)
    note_metadata = {"notes": {ref: note for note, ref in refs.items()}}
    original_json = json.dumps(table, ensure_ascii=False, separators=(",", ":"))
    compact_json = json.dumps([compact, note_metadata], ensure_ascii=False, separators=(",", ":"))
    if len(compact_json) < len(original_json):
        return compact, note_metadata
    return table, {}


def build_compact_fact_context(facts: Iterable[Fact], *, price_as_of=None) -> dict:
    """Factor repeated provenance; preserve every value, unit, qualifier and input ID.

    ``meta`` joins a row to ``fact_metadata.groups``. Group values override
    ``fact_metadata.default``; the group's source references ``sources``.
    ``note_ref`` points to an unchanged note in the same table's ``notes`` map.
    Dependency IDs need not have rows: callers can retrieve them with get_facts.
    """
    facts = sorted(facts, key=lambda fact: fact.id)
    data = [fact_for_model(fact, exclude_none=True) for fact in facts]
    dates = Counter(row["as_of"] for row in data)
    default_date = str(price_as_of) if price_as_of is not None else (
        max(dates, key=lambda day: (dates[day], day)) if dates else None)
    sources = {source: f"s{index}" for index, source in enumerate(sorted({row["source"] for row in data}))}
    groups, group_ids, rows = {}, {}, []
    for item in data:
        row = {"source_id": item.pop("id"), "label": item.pop("label"),
               "value": item.pop("value", None), "unit": item.pop("unit")}
        inputs = item.pop("inputs", [])
        if inputs:
            row["inputs"] = json.dumps(inputs, ensure_ascii=False, separators=(",", ":"))
        note = item.pop("note", None)
        # A standalone basis label duplicates report_basis exactly. Other notes,
        # including formulas, reported periods and uncertainty, remain verbatim.
        if note and (item.get("report_basis"), note) not in {("consolidated", "연결"), ("separate", "별도")}:
            row["note"] = note
        item.pop("url", None)
        if item.get("publisher") == item.get("source"):
            item.pop("publisher", None)
        if item.get("available_at") == item.get("published_at"):
            item.pop("available_at", None)
        if item["as_of"] == default_date:
            item.pop("as_of")
        item["source"] = sources[item["source"]]
        signature = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if signature not in group_ids:
            group_ids[signature] = f"m{len(groups)}"
            groups[group_ids[signature]] = item
        row["meta"] = group_ids[signature]
        rows.append(row)
    table, note_metadata = _compact_fact_rows(rows)
    return {
        "facts_csv": table,
        "fact_metadata": {
            "default": {"as_of": default_date} if default_date is not None else {},
            "sources": {key: source for source, key in sources.items()},
            "groups": groups,
            **note_metadata,
        },
    }


def build_news_context(snapshot: Snapshot) -> dict:
    ordered = {scope: ordered_news(snapshot, scope) for scope in NEWS_PREVIEW_TARGETS}
    events: set[str] = set()
    preview = {}
    for scope, facts in ordered.items():
        preview[scope] = _take_news(facts, NEWS_PREVIEW_TARGETS[scope], events)
    # Use any unfilled slots for additional articles from the other scope.
    remaining = sum(NEWS_PREVIEW_TARGETS.values()) - len(events)
    for scope, facts in ordered.items():
        if remaining == 0:
            break
        additional = _take_news(facts, remaining, events)
        preview[scope].extend(additional)
        remaining -= len(additional)

    news = {scope: [] for scope in ordered}
    for scope, facts in preview.items():
        for fact in facts:
            news[scope].append({
                "source_id": fact.id,
                "title": fact.label,
                "publisher": fact.publisher,
                "published_at": fact.published_at.isoformat() if fact.published_at else None,
                **({"event_id": fact.event_id} if fact.event_id else {}),
            })
    return {
        "market_news_csv": _record_table(news["market"], ("source_id", "title")),
        "stock_news_csv": _record_table(news["company"], ("source_id", "title")),
        "news_available": {scope: len(facts) for scope, facts in ordered.items()},
    }


def weekly_ohlcv(snapshot: Snapshot) -> list[dict]:
    start = chart_window_start(snapshot.as_of)
    bars = sorted((bar for bar in snapshot.series.stock_ohlcv if start <= bar.date <= snapshot.as_of),
                  key=lambda bar: bar.date)
    weekly = []
    for monday, rows in groupby(bars, key=lambda bar: week_start(bar.date)):
        week = list(rows)
        weekly.append({
            "week_start": monday.isoformat(), "last_trade_date": week[-1].date.isoformat(),
            "open": week[0].open, "high": max(bar.high for bar in week),
            "low": min(bar.low for bar in week), "close": week[-1].close,
            "volume": sum(bar.volume for bar in week),
        })
    return weekly


def build_shared_push(snapshot: Snapshot) -> dict:
    ids = core_fact_ids(snapshot)
    _, missing = expand_fact_ids(snapshot, ids)
    facts = [snapshot.facts[key] for key in sorted(ids)]
    return {
        "snapshot_id": snapshot.snapshot_id,
        "instrument": {"ticker": snapshot.ticker, "name": snapshot.name, "as_of": str(snapshot.as_of)},
        "time_context": {"decision_at": snapshot.decision_at.isoformat(),
                         "information_cutoff": snapshot.information_cutoff.isoformat()},
        "price_basis": snapshot.series.price_basis,
        **build_compact_fact_context(facts, price_as_of=snapshot.as_of),
        **build_news_context(snapshot),
        "data_status": snapshot.data_status,
        "warnings": snapshot.warnings,
        **({"missing_fact_ids": missing} if missing else {}),
    }


def build_moderator_context(snapshot: Snapshot, transcript: list[str]) -> dict:
    """Every non-news fact plus cited articles.

    The judge checks claims that debaters drew from lookups, so it starts from
    the whole snapshot rather than from what happened to be cited.
    """
    ids = {key for key, fact in snapshot.facts.items() if fact.category != "news"}
    for entry in transcript:
        record = history_entry(entry)
        ids.update(e["source_id"] for e in record.get("evidence", [])
                   if isinstance(e, dict) and isinstance(e.get("source_id"), str))
    _, missing = expand_fact_ids(snapshot, ids)
    facts = [snapshot.facts[key] for key in sorted(ids) if key in snapshot.facts]
    return {
        **build_compact_fact_context(facts, price_as_of=snapshot.as_of),
        **build_news_context(snapshot),
        "snapshot_id": snapshot.snapshot_id,
        "information_cutoff": snapshot.information_cutoff.isoformat(),
        "data_status": snapshot.data_status,
        "warnings": snapshot.warnings,
        "price_as_of": str(snapshot.as_of),
        "decision_at": snapshot.decision_at.isoformat(),
        **({"missing_fact_ids": missing} if missing else {}),
    }


def referenced_fact_context(snapshot: Snapshot, transcript: list[str]) -> dict:
    """Per-round supplement; shared facts stay in the immutable cache prefix."""
    ids = {e["source_id"] for entry in transcript for e in history_entry(entry).get("evidence", [])
           if isinstance(e, dict) and isinstance(e.get("source_id"), str)}
    _, missing = expand_fact_ids(snapshot, ids)
    shared_ids = core_fact_ids(snapshot)
    extra = [snapshot.facts[key] for key in sorted(ids - shared_ids) if key in snapshot.facts]
    compact = build_compact_fact_context(extra, price_as_of=snapshot.as_of) if extra else {}
    return {
        **({"referenced_facts_csv": compact["facts_csv"], "referenced_fact_metadata": compact["fact_metadata"]}
           if extra else {}),
        **({"missing_referenced_fact_ids": missing} if missing else {}),
    }
