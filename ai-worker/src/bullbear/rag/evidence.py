"""Explicit document search or structured Fact lookup; no natural-language routing."""
import math
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator
from ..snapshot import confirmed_date


class RequestBase(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, revalidate_instances='always')
    ticker: str = Field(pattern=r'^[0-9]{6}$')


class DocumentRequest(RequestBase):
    mode: Literal['documents'] = 'documents'
    question: str = Field(min_length=1, max_length=1000)

    @field_validator('question')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('search text must not be blank')
        return value


class FactRequest(RequestBase):
    mode: Literal['facts'] = 'facts'
    metric: Literal['close', 'per_ttm', 'pbr', 'roe_ttm', 'operating_margin_ttm', 'market_cap']
    as_of: date | None = None
    unit: Literal['KRW', 'KRW/share', '%', 'x', 'shares', 'count'] | None = None


EvidenceRequest = Annotated[DocumentRequest | FactRequest, Field(discriminator='mode')]
REQUEST_ADAPTER = TypeAdapter(EvidenceRequest)


def parse_request(value):
    return REQUEST_ADAPTER.validate_python(value)


METRICS = {
    'close': ('PX.CLOSE', 'KRW/share'),
    'per_ttm': ('VAL.PER_TTM', 'x'),
    'pbr': ('VAL.PBR', 'x'),
    'roe_ttm': ('VAL.ROE_TTM', '%'),
    'operating_margin_ttm': ('VAL.OP_MARGIN_TTM', '%'),
    'market_cap': ('VAL.MKTCAP', 'KRW'),
}


def assess(snapshot, request):
    request = parse_request(request)
    result = dict(version='explicit-evidence-v2', request=request.model_dump(mode='json'),
                  mode=request.mode, route='abstain', answerability='insufficient_evidence',
                  reasons=[], facts=[], snapshot_id=snapshot.snapshot_id)

    def reject(reason):
        result['reasons'] = [reason]
        return result

    if request.ticker != snapshot.ticker:
        return reject('ticker_mismatch')
    if isinstance(request, DocumentRequest):
        result.update(route='background', answerability='pending_document_search')
        return result
    name = request.metric
    fact_id, expected_unit = METRICS[name]
    result['metric'] = name
    if snapshot.created_at.utcoffset() is None:
        return reject('invalid_snapshot_cutoff')
    requested_date = request.as_of or snapshot.as_of
    if requested_date > confirmed_date(snapshot.created_at) or snapshot.as_of > confirmed_date(snapshot.created_at):
        return reject('unconfirmed_or_future_date')
    if request.unit is not None and request.unit != expected_unit:
        return reject('unit_mismatch')
    root = snapshot.facts.get(fact_id)
    if root is None:
        return reject('required_fact_missing')
    if root.unit != expected_unit:
        return reject('fact_unit_mismatch')
    if root.as_of != requested_date:
        return reject('fact_date_mismatch')
    seen, visiting, lineage = set(), set(), []

    def validate(key):
        if len(visiting) >= 128:
            return 'fact_dependency_depth_exceeded'
        if key in visiting:
            return 'cyclic_fact_dependencies'
        if key in seen:
            return None
        fact = snapshot.facts.get(key)
        if fact is None:
            return 'missing_fact_dependency'
        if fact.id != key or not fact.source.strip():
            return 'invalid_fact_identity_or_source'
        known_units = {spec[0]: spec[1] for spec in METRICS.values()}
        known_units.update({'VAL.SHARES': 'shares', 'VAL.NET_INCOME_TTM': 'KRW',
            'VAL.OPERATING_INCOME_TTM': 'KRW', 'VAL.REVENUE_TTM': 'KRW'})
        if key in known_units and fact.unit != known_units[key]:
            return 'dependency_unit_mismatch'
        if fact.value is None or not math.isfinite(fact.value) or fact.unit == 'text':
            return 'fact_value_unavailable'
        if fact.as_of > requested_date or fact.as_of > snapshot.as_of:
            return 'future_fact_dependency'
        if fact.published_at and (fact.published_at.utcoffset() is None or fact.published_at > snapshot.created_at):
            return 'fact_not_published_at_cutoff'
        if fact.source == 'derived' and not fact.inputs:
            return 'missing_fact_dependency'
        visiting.add(key)
        for dep in fact.inputs:
            reason = validate(dep)
            if reason:
                return reason
        visiting.remove(key)
        seen.add(key)
        lineage.append(key)
        return None

    reason = validate(fact_id)
    if reason:
        return reject(reason)
    if name == 'close' and root.value <= 0:
        return reject('invalid_price')
    result.update(route='facts', answerability='supported_fact', reasons=[],
                  facts=[dict(fact_id=root.id, ticker=snapshot.ticker, value=root.value, unit=root.unit,
                              as_of=root.as_of.isoformat(), source=root.source, inputs=list(root.inputs),
                              verified_lineage=lineage)])
    return result
