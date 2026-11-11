"""Public-speech views and on-demand analysis of canonical debate history.

Neither view replaces the history used for validation or storage. The initial
view preserves the public speech verbatim. Separately authored interpretation
details remain available through ``full_model_history`` for explicit lookup.
"""
from copy import deepcopy
import re

from .history import history_entry


def _value(value):
    return getattr(value, 'value', value)


def _record(entry):
    return deepcopy(entry) if isinstance(entry, dict) else history_entry(entry)


def _statement_data(statement):
    if hasattr(statement, 'model_dump'):
        return statement.model_dump(mode='json')
    return statement if isinstance(statement, dict) else {}


def _rebuttal(record):
    return (record.get('analysis') or {}).get('rebuttal') or record.get('rebuttal') or {}


def _related_records(records, *, role, side, round_kind, statement):
    if role == 'moderator' or round_kind in ('closing', 'extra'):
        return records
    if round_kind == 'opening':
        return []
    if role == 'debater':
        # Both openings provide the opponent's actual target and the speaker's
        # existing position. Later rounds above retain their full dependencies.
        return records
    if role != 'reviewer' or round_kind != 'rebuttal':
        return records

    current = _statement_data(statement)
    target = _rebuttal(current).get('target_statement_id')
    if not target or not any(r.get('statement_id') == target for r in records):
        return records  # Missing or legacy targets must not hide context.
    prose = '\n'.join(current.get(key, '') for key in ('claim', 'argument'))
    # Changes to the speaker's earlier position can require more than the
    # named opponent turn. Keep all history for such comparisons.
    if re.search(r'이전|앞서|당초|처음|기존|번복|수정|바꿨|바꾸|유지', prose):
        return records
    selected = {target}
    # Include any other turn quoted verbatim, including the speaker's own.
    quotes = re.findall(r'[“「『"]([^”」』"]{6,})[”」』"]', prose)
    for record in records:
        if any(quote in record.get(key, '') for quote in quotes for key in ('claim', 'argument')):
            selected.add(record.get('statement_id'))
    # A selected rebuttal may itself refer to an earlier turn.
    while True:
        dependencies = {_rebuttal(record).get('target_statement_id') for record in records
                        if record.get('statement_id') in selected}
        expanded = selected | (dependencies - {None})
        if expanded == selected:
            break
        selected = expanded
    return [record for record in records if record.get('statement_id') in selected]


def _compact_record(record):
    result = {key: deepcopy(record[key]) for key in
              ('statement_id', 'side', 'round', 'claim', 'argument')
              if record.get(key) is not None}
    analysis = record.get('analysis') or {}
    contexts = {item.get('evidence_ref'): item for item in analysis.get('interpretations', [])
                if isinstance(item, dict)}
    evidence = []
    for item in record.get('evidence', []):
        if not isinstance(item, dict):
            continue
        joined = {key: deepcopy(value) for key, value in item.items()
                  if key not in {'value', 'observation'} and value is not None}
        context = contexts.get(item.get('ref'), {})
        joined.update({key: deepcopy(value) for key, value in context.items()
                       if key != 'evidence_ref'})
        evidence.append(joined)
    result['evidence'] = evidence
    # Preserve unrecognised analysis fields for old/future records, rather than
    # silently dropping them. Only the joined interpretations are removed.
    result.update({key: deepcopy(value) for key, value in analysis.items()
                   if key != 'interpretations' and value is not None})
    unmatched = [deepcopy(item) for item in analysis.get('interpretations', [])
                 if isinstance(item, dict) and
                 item.get('evidence_ref') not in {e.get('ref') for e in evidence}]
    if unmatched:
        result['unmatched_interpretations'] = unmatched
    return result


def full_model_history(transcript):
    """Expose all authored interpretations and conditions for detail lookup.

    ``evidence`` owns its interpretation, expected outcome, assumptions and
    limitations; ``outlook``, ``rebuttal`` and ``closing`` belong to the turn.
    Fact observations and values are available separately from the snapshot.
    """
    return [_compact_record(record) for entry in transcript if (record := _record(entry))]


def model_history(transcript, *, role, side=None, round_kind=None, statement=None):
    """Return public speech and citations; private analysis requires lookup.

    This intentionally narrows the initial model context. It is not a lossless
    substitute for the full analysis. A model must fetch statement details when
    its judgment needs an assumption or limitation not stated in the speech.
    """
    if role not in {'debater', 'reviewer', 'moderator'}:
        raise ValueError(f'Unknown history role: {role}')
    records = [record for entry in transcript if (record := _record(entry))]
    selected = _related_records(records, role=role, side=_value(side),
                                round_kind=_value(round_kind), statement=statement)
    result = []
    for record in selected:
        view = {key: deepcopy(record[key]) for key in
                ('statement_id', 'side', 'round', 'claim', 'argument')
                if record.get(key) is not None}
        # Only the moderator emits interpretation IDs. Other roles refer to a
        # statement and its quote; the full IDs remain available in the detail.
        keys = ('ref', 'source_id', 'interpretation_id') if role == 'moderator' else ('ref', 'source_id')
        view['evidence'] = [{key: deepcopy(item[key]) for key in keys if item.get(key) is not None}
                            for item in record.get('evidence', []) if isinstance(item, dict)]
        rebuttal = _rebuttal(record)
        if rebuttal:
            view['rebuttal'] = {key: deepcopy(rebuttal[key])
                                for key in ('target_statement_id', 'target_quote') if key in rebuttal}
        result.append(view)
    return result
