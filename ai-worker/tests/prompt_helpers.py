"""Read logical inputs while keeping assertions on wire layout explicit in tests."""
import json


def initial_payload(conv):
    if not conv.system_in_messages:
        return json.loads(conv.messages[0]['content'])
    prefix, request = conv.messages[:2]
    assert prefix['role'] == request['role'] == 'user'
    block, = prefix['content']
    fixed = json.loads(block['text'])
    dynamic = json.loads(request['content'])
    assert not fixed.keys() & dynamic.keys()
    payload = {**fixed, **dynamic}
    codec = getattr(conv, 'context_ids', None)
    return codec.decode_response(payload) if codec is not None else payload
