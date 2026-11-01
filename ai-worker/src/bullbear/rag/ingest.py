"""Import captured provider items. No HTTP, scraping, LLM or implicit freshness claims."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from pydantic import ValidationError

from ..data.base import Disclosure, NewsArticle
from .schemas import CollectionBatch, DocumentInput, canonical_url
from .store import RagStore


def news_document(article: NewsArticle, *, observed_at: datetime, source: str = "naver-news",
                  ticker: str | None = None) -> DocumentInput:
    key = article.source_ref
    if key.lower().startswith(("http://", "https://")):
        key = canonical_url(key)
    return DocumentInput(source=source, source_item_id=key, kind="news", source_ref=article.source_ref,
                         url=article.url, title=article.title, text=article.summary,
                         publisher=article.publisher, tickers=(ticker,) if ticker else (),
                         published_at=article.published_at, timestamp_precision="instant",
                         content_level="title_summary" if article.summary else "title_only",
                         observed_at=observed_at, publication_verified=True, source_payload=asdict(article))


def disclosure_document(disclosure: Disclosure, *, observed_at: datetime, source: str = "opendart",
                        ticker: str | None = None) -> DocumentInput:
    return DocumentInput(source=source, source_item_id=disclosure.source_ref, kind="disclosure",
                         source_ref=disclosure.source_ref, url=disclosure.url, title=disclosure.title,
                         tickers=(ticker,) if ticker else (), published_on=disclosure.filed_on,
                         timestamp_precision="day", content_level="title_only", observed_at=observed_at,
                         publication_verified=True, metadata={"filer": disclosure.filer}, source_payload=asdict(disclosure))


def import_payload(store: RagStore, payload: dict):
    """Normalized v1 CollectionBatch; archive mode is the safe default for old files."""
    return store.import_collection(CollectionBatch.model_validate(payload))


def sync_payload(store: RagStore, payload: dict):
    """Convert a LOCAL captured NewsArticle/Disclosure batch, preserving invalid input.

    This is not a network collector. A producer must explicitly attest status,
    pages and coverage; the existing NAVER search method cannot attest complete
    archive coverage because its fixed page cap hides truncation.
    """
    return store.import_collection(normalize_capture(payload))


def normalize_capture(payload: dict) -> CollectionBatch:
    """Validate a captured provider response without writing to the archive."""
    data = dict(payload)
    kind = data.pop("kind")
    if kind not in {"news", "disclosure"}:
        raise ValueError("only captured news/disclosure provider records are supported")
    observed_at = data.pop("observed_at")
    ticker = data.pop("ticker", None)
    raw_items = data.pop("items", None)
    data["raw_payload"] = payload
    accepted = []
    invalid = not isinstance(raw_items, list)
    if not invalid:
        for raw in raw_items:
            try:
                if not isinstance(raw, dict):
                    raise ValueError("provider item must be an object")
                common = {"observed_at": observed_at, "source": data["source"], "ticker": ticker}
                if kind == "news":
                    accepted.append(news_document(NewsArticle(**raw), **common))
                else:
                    accepted.append(disclosure_document(Disclosure(**raw), **common))
            except (ValueError, TypeError, AttributeError, ValidationError):
                invalid = True
    data["items"] = accepted
    data["rejected_items"] = len(raw_items) - len(accepted) if isinstance(raw_items, list) else 0
    if invalid:
        data.update(status="partial" if accepted else "failed", coverage="partial" if accepted else "unknown",
                    safe_error="invalid_provider_item" if isinstance(raw_items, list) else "missing_items",
                    completed_through=None, cursor=None)
    return CollectionBatch.model_validate(data)
