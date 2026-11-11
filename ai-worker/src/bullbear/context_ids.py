"""Request-local identifiers; canonical IDs and prose stay in worker storage.

Only designated identifier fields and CSV columns are translated. In particular,
quoted speech is never searched/replaced, even when it equals an identifier.
"""
from copy import deepcopy
import csv
from io import StringIO
import json

from .history import history_entry


_FACT_FIELDS = {
    'source_id', 'source_ids', 'decisive_evidence', 'inputs', 'missing_fact_ids',
    'missing_source_ids', 'remaining_source_ids', 'oversized_source_ids',
}
_STATEMENT_FIELDS = {'statement_id', 'target_statement_id'}
_INTERPRETATION_FIELDS = {'interpretation_id', 'key_interpretation_ids', 'keys'}
_PROSE_FIELDS = {
    'claim', 'argument', 'target_quote', 'quote', 'interpretation', 'assumptions',
    'limitations', 'limits', 'acknowledged', 'reason', 'unresolved', 'retained',
    'conceded', 'outlook_reason', 'uncertainties', 'change_conditions', 'comment',
    'comments', 'reasoning', 'common_ground', 'core_issues', 'disagreements',
    'unverified', 'outlook_basis', 'outlook_limits', 'instruction', 'task',
    'review_instructions', 'statement_output_instructions', 'output_instructions',
    'system', 'summary', 'text', 'note', 'label', 'title', 'description', 'warnings',
}
_FACT_MAP_FIELDS = {'news_lookup_results', 'facts', 'facts_by_id'}


def _aliases(values, prefix, reserved):
    result, number = {}, 1
    for value in dict.fromkeys(values):
        while f'{prefix}{number}' in reserved:
            number += 1
        result[value] = f'{prefix}{number}'
        number += 1
    return result


def _map_ids(value, mapping):
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_map_ids(item, mapping) for item in value]
    return deepcopy(value)


class RequestIds:
    def __init__(self, snapshot, transcript):
        records = [entry if isinstance(entry, dict) else history_entry(entry) for entry in transcript]
        statements = [r['statement_id'] for r in records if isinstance(r.get('statement_id'), str)]
        interpretations = [e['interpretation_id'] for r in records for e in r.get('evidence', [])
                           if isinstance(e, dict) and isinstance(e.get('interpretation_id'), str)]
        facts = sorted(snapshot.facts)
        reserved = set(facts) | set(statements) | set(interpretations)
        # Fact aliases are stable across every request for a frozen snapshot.
        # Turn aliases retain transcript order as later accepted turns are added.
        self.fact_ids = _aliases(facts, '@F', reserved)
        self.statement_ids = _aliases(statements, '@S', reserved)
        self.interpretation_ids = _aliases(interpretations, '@I', reserved)

    def _maps(self, decode):
        maps = (self.fact_ids, self.statement_ids, self.interpretation_ids)
        return tuple({alias: canonical for canonical, alias in mapping.items()} for mapping in maps) if decode else maps

    @staticmethod
    def _field_map(key, maps):
        if key in _FACT_FIELDS:
            return maps[0]
        if key in _STATEMENT_FIELDS:
            return maps[1]
        if key in _INTERPRETATION_FIELDS:
            return maps[2]
        if key == 'id':
            return {**maps[0], **maps[1], **maps[2]}
        return None

    def _csv(self, value, maps):
        rows = list(csv.reader(StringIO(value, newline='')))
        if not rows:
            return value
        columns = [(index, self._field_map(name, maps)) for index, name in enumerate(rows[0])]
        columns = [(index, mapping) for index, mapping in columns if mapping is not None]
        if not columns:
            return value
        for row in rows[1:]:
            for index, mapping in columns:
                if index >= len(row) or not row[index]:
                    continue
                cell = row[index]
                if cell.startswith('['):
                    try:
                        decoded = json.loads(cell)
                    except ValueError:
                        continue
                    if isinstance(decoded, list):
                        row[index] = json.dumps(_map_ids(decoded, mapping), ensure_ascii=False, separators=(',', ':'))
                else:
                    row[index] = mapping.get(cell, cell)
        ending = '\r\n' if '\r\n' in value else '\n'
        stream = StringIO(newline='')
        writer = csv.writer(stream, lineterminator=ending)
        writer.writerows(rows)
        result = stream.getvalue()
        return result if value.endswith(('\n', '\r')) else result.removesuffix(ending)

    def _walk(self, value, maps):
        if isinstance(value, list):
            return [self._walk(item, maps) for item in value]
        if not isinstance(value, dict):
            return deepcopy(value)
        result = {}
        for key, item in value.items():
            mapping = self._field_map(key, maps)
            if key in _PROSE_FIELDS:
                result[key] = deepcopy(item)
            elif mapping is not None:
                result[key] = _map_ids(item, mapping)
            elif key.endswith('_csv') and isinstance(item, str):
                result[key] = self._csv(item, maps)
            elif key in _FACT_MAP_FIELDS and isinstance(item, dict):
                result[key] = {maps[0].get(source, source): self._walk(record, maps)
                               for source, record in item.items()}
            elif key == 'evidence' and isinstance(item, list):
                # Canonical/statement-wire objects, or verdict-wire source IDs.
                result[key] = [self._walk(record, maps) if isinstance(record, dict)
                               else _map_ids(record, maps[0]) for record in item]
            elif key == 'rebuttal' and isinstance(item, list):
                result[key] = ([_map_ids(item[0], maps[1]), *deepcopy(item[1:])] if item else [])
            elif key == 'reviews' and isinstance(item, list):
                result[key] = [([_map_ids(row[0], maps[1]), *deepcopy(row[1:3]),
                                 *_map_ids(row[3:], maps[0])] if isinstance(row, list) and row else
                                self._walk(row, maps)) for row in item]
            elif key == 'value' and isinstance(value.get('path'), str):
                # Reviewer patches carry typed IDs in value only at named ID paths.
                field = value['path'].rsplit('.', 1)[-1]
                patch_map = self._field_map(field, maps)
                result[key] = _map_ids(item, patch_map) if patch_map is not None else deepcopy(item)
            else:
                result[key] = self._walk(item, maps)
        return result

    def encode_context(self, value):
        """Return a fresh model-only view without changing any prose."""
        return self._walk(value, self._maps(False))

    def decode_response(self, value):
        """Restore known aliases; unknown values remain for canonical validation."""
        return self._walk(value, self._maps(True))

    def decode_tool_arguments(self, name, arguments):
        decoded = self.decode_response(arguments)
        if name == 'read_snapshot' and isinstance(decoded, dict) and decoded.get('kind') == 'facts':
            decoded['args'] = _map_ids(decoded.get('args'), self._maps(True)[0])
        return decoded

    def encode_tool_result(self, result):
        if not isinstance(result, str):
            return self.encode_context(result)
        try:
            value = json.loads(result)
        except ValueError:
            return result  # A plain-text error is prose, not an identifier field.
        return json.dumps(self.encode_context(value), ensure_ascii=False, separators=(',', ':'))

    def wrap_tool_handler(self, handler):
        def wrapped(name, arguments):
            return self.encode_tool_result(handler(name, self.decode_tool_arguments(name, arguments)))
        return wrapped
