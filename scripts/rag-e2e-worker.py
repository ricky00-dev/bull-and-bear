"""Launch the real worker for local RAG integration checks with outbound traffic blocked.

Requires PYTHONPATH=ai-worker/src and RAG_E2E_DATA pointing to prepared copied data.
No retrieval/provider responses are replaced. The normal FastAPI app and storage run.
"""
import ipaddress
import json
import os
from pathlib import Path
import sys

directory = Path(os.environ['RAG_E2E_DATA']).resolve()
manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
audit_path = directory / 'worker-network-audit.jsonl'

def record(value):
    with audit_path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value) + '\n')

def audit(event, args):
    if event != 'socket.connect':
        return
    address = args[1]
    host = address[0] if isinstance(address, tuple) else ''
    try:
        allowed = ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    record({'event': event, 'allowed': allowed, 'host': host})
    if not allowed:
        raise RuntimeError('External network disabled for RAG integration verification')

sys.addaudithook(audit)
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
for key in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'KRX_API_KEY', 'OPENDART_API_KEY',
            'NAVER_CLIENT_ID', 'NAVER_CLIENT_SECRET'):
    os.environ[key] = ''
for key, value in {
    'BULLBEAR_DATA_DIR': str(directory), 'BULLBEAR_RAG_ENABLED': 'true',
    'BULLBEAR_RAG_GENERATION_ID': manifest['generation_id'],
    'BULLBEAR_RAG_ARCHIVE_BACKEND': 'sqlite', 'BULLBEAR_RAG_CONTEXT_BACKEND': 'sqlite',
    'BULLBEAR_RAG_OBJECT_BACKEND': 'local', 'BULLBEAR_RAG_SHADOW_ENABLED': 'false',
    'BULLBEAR_RAG_SHADOW_PREPARE_QUERY': 'false', 'BULLBEAR_RAG_SELECTION_POLICY': '',
}.items():
    os.environ[key] = value

import uvicorn
from fastapi.responses import JSONResponse
from bullbear.server.app import create_app

app = create_app()

@app.middleware('http')
async def read_only(request, call_next):
    if (request.method, request.url.path) not in {
        ('GET', '/health'), ('POST', '/rag/search'), ('POST', '/rag/facts'),
    }:
        record({'event': 'blocked_route', 'path': request.url.path})
        return JSONResponse({'error': {'code': 'E2E_READ_ONLY', 'message': 'Only saved RAG queries allowed'}}, status_code=403)
    response = await call_next(request)
    record({'event': 'request', 'path': request.url.path, 'status': response.status_code})
    return response

uvicorn.run(app, host='127.0.0.1', port=int(os.getenv('RAG_E2E_WORKER_PORT', '18000')))
