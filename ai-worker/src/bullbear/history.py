"""Read canonical JSON history and previously saved text/JSON transcripts."""
import json
import re

MARKER = "\n구조화 정보: "


def structured_record(entry):
    if not isinstance(entry, str):
        return None
    # Decode JSON first: a quoted legacy marker in prose is ordinary data.
    try:
        record = json.loads(entry)
    except (ValueError, TypeError):
        if MARKER not in entry:
            return None
        try:
            record = json.loads(entry.rsplit(MARKER, 1)[1])
        except (ValueError, TypeError):
            return None
    return record if isinstance(record, dict) else None


def history_entry(entry):
    """Extract speaker, actual prose and local refs without searching evidence prose."""
    record = structured_record(entry)
    if record is not None:
        return record
    if not isinstance(entry, str):
        return {}
    header = re.match(r'^\[([^\]]+)\] (매수|매도) 측\n', entry)
    if not header:
        return {}
    body, _, evidence = entry[header.end():].partition('\n근거:\n')
    claim, _, argument = body.partition('\n')
    return {
        'side': {'매수': 'bull', '매도': 'bear'}[header[2]],
        'claim': claim.removeprefix('주장: '), 'argument': argument,
        'evidence': [{'ref': ref, 'source_id': source}
                     for ref, source in re.findall(r'^\s+(E\d+): (\S+) =', evidence, re.M)],
    }


def reference_map(record):
    return {e['ref']: e['source_id'] for e in record.get('evidence', [])
            if isinstance(e, dict) and isinstance(e.get('ref'), str)
            and isinstance(e.get('source_id'), str)}


def contains_quote(record, quote):
    return any(isinstance(record.get(key), str) and quote in record[key]
               for key in ('claim', 'argument'))
