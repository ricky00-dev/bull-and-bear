"""Opt-in relevance gates. Thresholds belong to one embedding version, not all models."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .index import normalize
from .schemas import digest


class SelectionPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    version: Literal['focused-evidence-v1'] = 'focused-evidence-v1'
    embedding_version: str | None = None
    max_distance: float = Field(default=0.45, ge=0, le=2, allow_inf_nan=False)
    distance_band: float = Field(default=0.08, ge=0, le=2, allow_inf_nan=False)
    lexical_score_ratio: float = Field(default=0.5, gt=0, le=1, allow_inf_nan=False)
    max_items: int = Field(default=2, ge=1, le=5)

    @property
    def policy_id(self):
        return 'SEL.' + digest(self.model_dump(mode='json'))


# Query scaffolding is not evidence of relevance. Keep the original label order
# for semantic embeddings; headlines and generated analysis never become queries.
STOP = frozenset('무엇 무엇인가 어떻게 어떤 설명 설명해 알려줘 알려주세요 있나 있는 대한 대해 의미 뜻 왜 이 그 그리고 또는 은 는 이 가 을 를 의 에 와 과 도'.split())


def focused_query(snapshot):
    labels = list(dict.fromkeys(f.label.strip() for _, f in sorted(snapshot.facts.items())
                               if f.category not in {'news', 'disclosure'} and f.label.strip()))
    return ' '.join(labels)[:2000]


def focused_terms(snapshot):
    from .retrieval import ALIASES, _ALIAS_PATTERNS
    text = focused_query(snapshot).lower()
    tokens = {t for t in normalize(text) if len(t) > 1 and not t.isdecimal() and t not in STOP}
    for concept, aliases in ALIASES.items():
        if _ALIAS_PATTERNS[concept].search(text):
            tokens.update(a for a in aliases if a not in {'valuation', 'earnings', 'profitability'})
    return sorted(tokens)[:128]


def query_text(snapshot, policy=None):
    if policy is not None:
        return focused_query(snapshot)
    from .retrieval import query_terms
    return ' '.join(query_terms(snapshot))


def gate(policy, strategy, member, row, terms, best_distance, best_lexical):
    if strategy != 'bm25':
        distance = row['cosine_distance']
        if distance > policy.max_distance:
            return 'below_relevance_threshold'
        if distance > best_distance + policy.distance_band:
            return 'outside_best_evidence_band'
    else:
        content = set(normalize(member['title'] + ' ' + member['text']))
        if not content.intersection(terms):
            return 'no_content_overlap'
        if abs(row['score']) < best_lexical * policy.lexical_score_ratio:
            return 'below_lexical_score_band'
    return 'selected'
