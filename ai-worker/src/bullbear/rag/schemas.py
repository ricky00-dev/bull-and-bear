"""Version 1 archive boundary. All observation times must include a timezone."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Horizon = Literal["common", "short", "medium", "long"]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(timezone.utc)


def stamp(value: datetime) -> str:
    return utc(value).isoformat(timespec="microseconds")


def canonical_url(value: str) -> str:
    """Only normalize scheme/host and fragment; query parameters may identify articles."""
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("source URL must be public HTTP(S) without credentials")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Period(FrozenModel):
    value: int = Field(gt=0)
    unit: Literal["trading_day", "calendar_day", "month", "year"]


class StudyScope(FrozenModel):
    market: str | None = None
    sample_start: date | None = None
    sample_end: date | None = None
    forecast_horizon: Period | None = None
    holding_period: Period | None = None
    decision_frequency: Period | None = None
    outcome_window: Period | None = None
    outcome_metric: str | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.sample_start and self.sample_end and self.sample_start > self.sample_end:
            raise ValueError("invalid study sample interval")
        return self


class DocumentInput(FrozenModel):
    source: str = Field(min_length=1, max_length=100)
    source_item_id: str = Field(min_length=1, max_length=2000)
    kind: Literal["news", "disclosure", "knowledge", "research"]
    source_ref: str = Field(min_length=1, max_length=2000)
    url: str
    title: str = Field(min_length=1)
    text: str = ""
    publisher: str | None = None
    tickers: tuple[str, ...] = ()
    unit: str = "text"
    published_at: datetime | None = None
    published_on: date | None = None
    source_updated_at: datetime | None = None
    timestamp_precision: Literal["instant", "day", "unknown"] = "unknown"
    content_level: Literal["title_only", "title_summary", "full_text"] = "title_only"
    observed_at: datetime
    publication_verified: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_payload: dict[str, Any] = Field(default_factory=dict)

    _url = field_validator("url")(canonical_url)

    @field_validator("tickers")
    @classmethod
    def ticker_set(cls, value):
        return tuple(sorted(set(value)))

    @field_validator("observed_at", "published_at", "source_updated_at")
    @classmethod
    def aware(cls, value):
        return utc(value) if value is not None else None

    @field_validator("source", "source_item_id", "source_ref", "title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    @model_validator(mode="after")
    def coherent(self):
        if self.timestamp_precision == "instant" and self.published_at is None:
            raise ValueError("instant precision requires published_at")
        if self.timestamp_precision == "day" and (self.published_on is None or self.published_at is not None):
            raise ValueError("day precision requires published_on and no invented published_at")
        if self.timestamp_precision == "unknown" and (self.published_at is not None or self.published_on is not None):
            raise ValueError("publication timestamp precision must be explicit")
        if self.content_level == "title_only" and self.text:
            raise ValueError("title_only must not contain body text")
        if self.content_level != "title_only" and not self.text.strip():
            raise ValueError("summary/full_text requires nonempty text")
        canonical_json(self.model_dump(mode="json"))
        return self

    def content(self) -> dict:
        # Observation/import metadata must not create new content revisions.
        return self.model_dump(mode="json", exclude={"observed_at", "source_payload"})

    @property
    def document_id(self) -> str:
        return "D." + digest([self.source, self.source_item_id])

    @property
    def content_hash(self) -> str:
        return digest(self.content())

    @property
    def revision_id(self) -> str:
        return "R." + digest([self.document_id, self.content_hash])


class CollectionBatch(FrozenModel):
    collection_id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=100)
    query_key: str = Field(min_length=1, max_length=500)
    window_start: datetime
    window_end: datetime
    started_at: datetime
    finished_at: datetime
    observation_mode: Literal["current", "archive"] = "archive"
    status: Literal["completed", "empty", "partial", "failed"]
    coverage: Literal["complete", "partial", "unknown"]
    pages: int = Field(ge=0)
    items: tuple[DocumentInput, ...] = ()
    safe_error: str | None = Field(default=None, pattern=r"^[a-z0-9_:-]{1,100}$")
    completed_through: datetime | None = None
    cursor: str | None = None
    rejected_items: int = Field(default=0, ge=0)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("window_start", "window_end", "started_at", "finished_at", "completed_through")
    @classmethod
    def aware(cls, value):
        return utc(value) if value is not None else None

    @model_validator(mode="after")
    def coherent(self):
        if self.window_start > self.window_end or self.started_at > self.finished_at:
            raise ValueError("invalid collection interval")
        if any(i.source != self.source or not self.started_at <= i.observed_at <= self.finished_at for i in self.items):
            raise ValueError("items must match source and collection observation interval")
        complete = self.status in {"completed", "empty"}
        if complete and (self.coverage != "complete" or self.pages < 1 or self.safe_error):
            raise ValueError("complete collection requires a confirmed response and complete coverage")
        if complete and self.rejected_items:
            raise ValueError("a complete collection cannot have rejected items")
        if self.status == "empty" and self.items or self.status == "completed" and not self.items:
            raise ValueError("empty and completed distinguish confirmed empty and nonempty results")
        if self.status == "failed" and (self.items or not self.safe_error or self.coverage != "unknown"):
            raise ValueError("failed collection requires no accepted items, unknown coverage and a safe error")
        if self.status == "partial" and (self.coverage != "partial" or not self.safe_error):
            raise ValueError("partial collection requires partial coverage and a safe reason")
        if self.completed_through is not None:
            if not complete or self.observation_mode != "current":
                raise ValueError("only complete current collections may advance a watermark")
            if not self.window_start <= self.completed_through <= self.window_end:
                raise ValueError("watermark is outside the confirmed window")
        return self


class CollectionResult(FrozenModel):
    collection_id: str
    status: str
    imported_items: int
    new_revisions: int
    new_events: int
    quarantined_items: int
    rejected_items: int = 0
    watermark_advanced: bool
    watermark_reason: str
    reused: bool = False


class ChunkInput(FrozenModel):
    revision_id: str
    ordinal: int = Field(ge=0)
    text: str = Field(min_length=1)
    source_locator: str = Field(min_length=1)
    chunker_version: str = Field(min_length=1)

    @property
    def chunk_id(self):
        return "C." + digest(self.model_dump(mode="json"))


class AnnotationInput(FrozenModel):
    chunk_id: str
    horizons: tuple[Horizon, ...] = ()
    topics: tuple[str, ...] = ()
    tickers: tuple[str, ...] = ()
    markets: tuple[str, ...] = ()
    event_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    study_scope: StudyScope | None = None
    applicability: str = ""
    limitations: tuple[str, ...] = ()
    duplicate_group_id: str | None = None
    review_status: Literal["proposed", "approved", "rejected"]
    created_at: datetime
    reviewed_at: datetime | None = None
    tagging_policy_version: str = Field(min_length=1)

    @field_validator("created_at", "reviewed_at", "event_at", "valid_from", "valid_until")
    @classmethod
    def aware(cls, value):
        return utc(value) if value is not None else None

    @model_validator(mode="after")
    def coherent(self):
        if len(set(self.horizons)) != len(self.horizons):
            raise ValueError("horizon tags must be unique")
        if self.review_status == "proposed" and self.reviewed_at is not None:
            raise ValueError("proposed annotations have not been reviewed")
        if self.review_status != "proposed" and (self.reviewed_at is None or self.reviewed_at < self.created_at):
            raise ValueError("reviewed annotations require a review timestamp at/after creation")
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValueError("annotation validity interval must be nonempty")
        return self
