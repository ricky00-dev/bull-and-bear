"""On-demand authored analysis from this debate's immutable accepted turns."""
from copy import deepcopy
import json

from .interpretations import history_records


STATEMENT_DETAIL_TOOL = {
    'name': 'get_statement_details',
    'description': '이 토론의 확정 발언 하나에서 근거별 해석·가정·한계·인정·반박·변경 조건 전체를 읽는다.',
    'input_schema': {'type': 'object', 'properties': {'statement_id': {'type': 'string'}},
                     'required': ['statement_id'], 'additionalProperties': False},
}


class HistoryLookup:
    def __init__(self, transcript):
        self.records = {r['statement_id']: r for r in history_records(transcript) if r.get('statement_id')}

    def __call__(self, arguments):
        if not isinstance(arguments, dict) or set(arguments) != {'statement_id'}:
            raise ValueError('statement_id 하나를 지정하세요')
        key = arguments['statement_id']
        if not isinstance(key, str) or key not in self.records:
            raise ValueError('현재 토론의 확정 발언 ID만 조회할 수 있습니다')
        record = deepcopy(self.records[key])
        for evidence in record.get('evidence', []):
            evidence.pop('observation', None)
        return json.dumps(record, ensure_ascii=False, separators=(',', ':'))
