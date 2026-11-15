"""Optional macro observations with point-in-time availability evidence."""
from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

DataStatus = Literal["OK", "EMPTY", "FAILED", "UNSUPPORTED", "STALE", "AVAILABILITY_UNVERIFIED"]
MacroUnit = Literal["index_points", "USD/bbl", "%"]

# Fact ID, original series, label, unit, maximum age in calendar days.
FRED_SERIES = (
    ("MACRO.VIX", "VIXCLS", "VIX", "index_points", 7),
    ("MACRO.WTI_SPOT", "DCOILWTICO", "WTI 쿠싱 현물가", "USD/bbl", 14),
    ("MACRO.FED_TARGET_LOWER", "DFEDTARL", "연준 목표금리 하한", "%", 14),
    ("MACRO.FED_TARGET_UPPER", "DFEDTARU", "연준 목표금리 상한", "%", 14),
)
BOK_RATE = "MACRO.BOK_BASE_RATE"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
ECOS_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
FRED_TZ = ZoneInfo("America/Chicago")


@dataclass(frozen=True)
class MacroReading:
    source_id: str
    label: str
    unit: MacroUnit
    source: str
    status: DataStatus
    value: float | None = None
    observation_date: date | None = None
    available_at: datetime | None = None
    vintage_date: date | None = None

    def available_by(self, cutoff: datetime) -> bool:
        if (self.status not in ("OK", "STALE") or self.value is None or not math.isfinite(self.value)
                or self.observation_date is None or self.observation_date > cutoff.date()):
            return False
        if self.available_at is not None:
            return self.available_at.utcoffset() is not None and self.available_at <= cutoff
        return (self.source.startswith("FRED:") and self.vintage_date is not None
                and self.observation_date <= self.vintage_date < cutoff.astimezone(FRED_TZ).date())


class MacroSource:
    def __init__(self, fred_key: str | None, ecos_key: str | None, cache_dir: Path, *,
                 vix_enabled: bool = False, client: httpx.Client | None = None, clock=None):
        self.fred_key = fred_key
        self.ecos_key = ecos_key
        self.vix_enabled = vix_enabled
        self.cache_path = cache_dir / "ecos-base-rate.sqlite3"
        self._http = client if client is not None else httpx.Client(timeout=5)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def close(self):
        self._http.close()

    def collect(self, cutoff: datetime) -> list[MacroReading]:
        readings = [self._fred(cutoff, *spec) for spec in FRED_SERIES]
        readings.append(self._ecos(cutoff))
        return readings

    def _fred(self, cutoff, fact_id, series, label, unit, max_age):
        source = f"FRED:{series}"
        if not self.fred_key or (series == "VIXCLS" and not self.vix_enabled):
            return MacroReading(fact_id, label, unit, source, "UNSUPPORTED")
        # FRED proves availability by date. Use a completed source calendar
        # day so an intraday Korean cutoff never relies on a same-day vintage.
        vintage = cutoff.astimezone(FRED_TZ).date() - timedelta(days=1)
        try:
            response = self._http.get(FRED_URL, params={
                "api_key": self.fred_key, "file_type": "json", "series_id": series,
                "observation_start": str(vintage - timedelta(days=45)), "observation_end": str(vintage),
                "realtime_start": str(vintage), "realtime_end": str(vintage),
                "sort_order": "desc", "limit": 46,
            })
            response.raise_for_status()
            payload = response.json()
            if (date.fromisoformat(payload["realtime_start"]) != vintage
                    or date.fromisoformat(payload["realtime_end"]) != vintage):
                raise ValueError("Unexpected FRED vintage")
            rows = payload["observations"]
            if not isinstance(rows, list):
                raise ValueError("Invalid observations")
            eligible = {}
            uncertain = False
            for row in rows:
                if row["value"] == ".":
                    continue
                day = date.fromisoformat(row["date"])
                if (day > vintage or date.fromisoformat(row["realtime_start"]) > vintage
                        or date.fromisoformat(row["realtime_end"]) < vintage):
                    uncertain = True
                    continue
                value = _finite(row["value"])
                if day in eligible and eligible[day] != value:
                    raise ValueError("Conflicting FRED observations")
                eligible[day] = value
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return MacroReading(fact_id, label, unit, source, "FAILED")
        if not eligible:
            return MacroReading(fact_id, label, unit, source,
                                "AVAILABILITY_UNVERIFIED" if uncertain else "EMPTY")
        day = max(eligible)
        value = eligible[day]
        status = "STALE" if (cutoff.date() - day).days > max_age else "OK"
        return MacroReading(fact_id, label, unit, source, status, value, day, vintage_date=vintage)

    def _ecos(self, cutoff):
        label, source = "한국은행 기준금리", "ECOS:722Y001/0101000"
        if not self.ecos_key:
            return MacroReading(BOK_RATE, label, "%", source, "UNSUPPORTED")
        until = min(cutoff.date(), self._clock().astimezone(cutoff.tzinfo).date())
        start = until - timedelta(days=30)
        failed = False
        rows = []
        try:
            response = self._http.get(
                f"{ECOS_URL}/{quote(self.ecos_key, safe='')}/json/kr/1/31/722Y001/D/"
                f"{start:%Y%m%d}/{until:%Y%m%d}/0101000")
            response.raise_for_status()
            body = response.json()
            if body.get("RESULT", {}).get("CODE") != "INFO-200":
                for row in body["StatisticSearch"]["row"]:
                    if row["STAT_CODE"] != "722Y001" or row["ITEM_CODE1"] != "0101000":
                        raise ValueError("Unexpected ECOS series")
                    day = datetime.strptime(row["TIME"], "%Y%m%d").date()
                    if start <= day <= until:
                        rows.append((str(day), _finite(row["DATA_VALUE"])))
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            rows = []
            failed = True
        observed_at = self._clock().astimezone(timezone.utc).isoformat()
        # ECOS provides observation dates but no vintage or publication time.
        # Record when this worker actually saw each value for later cutoffs.
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.cache_path)) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS rates (day TEXT, value REAL, observed_at TEXT, "
                           "PRIMARY KEY (day, observed_at))")
                db.executemany(
                    "INSERT OR IGNORE INTO rates SELECT :day, :value, :time WHERE :value IS NOT "
                    "(SELECT value FROM rates WHERE day=:day AND observed_at<=:time "
                    "ORDER BY observed_at DESC LIMIT 1)",
                    [{"day": day, "value": value, "time": observed_at} for day, value in rows])
                observed = db.execute(
                    "SELECT day, value, observed_at FROM rates WHERE day<=? AND observed_at<=? "
                    "ORDER BY day DESC, observed_at DESC LIMIT 1",
                    (str(cutoff.date()), cutoff.astimezone(timezone.utc).isoformat())).fetchone()
        except (OSError, sqlite3.Error):
            return MacroReading(BOK_RATE, label, "%", source, "FAILED")
        if observed is None:
            status = "FAILED" if failed else "AVAILABILITY_UNVERIFIED" if rows else "EMPTY"
            return MacroReading(BOK_RATE, label, "%", source, status)
        day, value, known = observed
        day = date.fromisoformat(day)
        status = "STALE" if failed or (cutoff.date() - day).days > 7 else "OK"
        return MacroReading(BOK_RATE, label, "%", source, status, value, day, datetime.fromisoformat(known))


def _finite(raw):
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("Nonfinite macro observation")
    return value
