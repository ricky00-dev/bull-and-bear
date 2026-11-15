"""Bounded, deterministic selection of headlines already returned by NAVER."""
import hashlib
import re
from datetime import timedelta
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit

from .naver_news import MARKET_TOPICS


def select_news(articles, start, end, *, limit, scope, already_selected=(), event_dedupe=False):
    """Keep one representative per URL, normalized headline or near-identical event."""
    eligible = [a for a in articles if a.published_at.utcoffset() is not None
                and start <= a.published_at <= end and a.title.strip()]

    def rank(article):
        importance = sum(any(alias in article.title for alias in aliases) for _, aliases in MARKET_TOPICS)
        return (importance if scope == "market" else 0, article.published_at, article.source_ref)

    selected = []
    representatives = list(already_selected)
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
        if event_dedupe and any(_same_event(article, known) for known in representatives):
            continue
        representatives.append(article)
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


def _same_event(a, b):
    """Conservative same-day syndication heuristic, without external/LLM calls.

    Shared company names alone are insufficient: require a second title anchor
    and substantial overlap in the search summaries. Empty summaries never match.
    """
    if abs(a.published_at - b.published_at) > timedelta(days=1):
        return False
    words = lambda title: {w.casefold() for w in re.findall(r"[가-힣A-Za-z0-9]+", title) if len(w) >= 3}
    anchors = len(words(a.title) & words(b.title))
    if anchors < 2:
        return False
    left, right = _headline(a.summary), _headline(b.summary)
    if min(len(left), len(right)) < 60:
        return False
    shingles = lambda text: {text[i:i + 3] for i in range(len(text) - 2)}
    x, y = shingles(left), shingles(right)
    overlap = len(x & y) / min(len(x), len(y))
    # Syndicated roundups can append unrelated paragraphs. Multiple shared
    # title anchors allow partial summary overlap without matching on company alone.
    return overlap >= 0.65 or (anchors >= 3 and overlap >= 0.35)
