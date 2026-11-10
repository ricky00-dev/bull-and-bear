"""Bounded, deterministic selection of headlines already returned by NAVER."""
import hashlib
import re
from datetime import timedelta
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit

from .naver_news import MARKET_TOPICS


def select_news(articles, start, end, *, limit, scope, already_selected=()):
    """Keep one representative per URL, normalized headline or near-identical event."""
    eligible = [a for a in articles if a.published_at.utcoffset() is not None
                and start <= a.published_at <= end and a.title.strip()]

    def rank(article):
        importance = sum(any(alias in article.title for alias in aliases) for _, aliases in MARKET_TOPICS)
        return (importance if scope == "market" else 0, article.published_at, article.source_ref)

    selected = []
    seen = [(_canonical_url(a.url), _headline(a.title), a.published_at) for a in already_selected]
    for article in sorted(eligible, key=rank, reverse=True):
        if len(selected) >= limit:
            break
        url, headline = _canonical_url(article.url), _headline(article.title)
        if any(url == known_url or headline == known_headline or (
                abs(article.published_at - published) <= timedelta(days=1)
                and min(len(headline), len(known_headline)) >= 12
                and SequenceMatcher(None, headline, known_headline, autojunk=False).ratio() >= 0.85
        ) for known_url, known_headline, published in seen):
            continue
        seen.append((url, headline, article.published_at))
        event_id = "EVT." + hashlib.sha256(headline.encode()).hexdigest()[:16]
        selected.append((article, event_id))
    return selected


def _headline(title):
    title = re.sub(r"^\s*[\[【(][^\]】)]{1,10}[\]】)]\s*", "", title)
    return re.sub(r"[\W_]+", "", title.casefold()) or title


def _canonical_url(url):
    try:
        parts = urlsplit(url)
        params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                  if not k.casefold().startswith("utm_")]
        return (parts.hostname, parts.path.rstrip("/"), urlencode(sorted(params)))
    except ValueError:
        return url
