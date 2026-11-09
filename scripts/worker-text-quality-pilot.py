"""Generate up to three review debates from frozen snapshots, with durable budgeting.

Uses the production LiveRunner without touching the HTTP server or its store.
No automatic batch restart or whole-debate retry; failed attempts remain visible.
"""
from pathlib import Path
import argparse
from dataclasses import replace
import hashlib
import json
import time

from dotenv import load_dotenv

from bullbear.audit import RunAudit, selected_models
from bullbear.anthropic_budget import WorkerSpendLedger
from bullbear.config import load_settings
from bullbear.events import EventLog
from bullbear.server.service import LiveRunner
from bullbear.snapshot import Snapshot


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def render(directory, records):
    lines = ['# 실제 워커 토론 3건 — 텍스트 품질 검토', '',
             '저장된 실제 공급자 스냅샷을 이용한 새 생성입니다. 오늘 시황이나 과거 시점 백테스트가 아닙니다.',
             '주가 기준일과 자료 수집 시각이 다릅니다. 새 시장 조회·RAG 검색은 하지 않았습니다.',
             '아래 출력은 교정하지 않은 모델 원문입니다. 코드 검사 통과는 논리·예측 정확성 보장이 아닙니다.',
             '발언은 argument 한 문단만 표시합니다. 내부 요약 claim과 근거별 해석은 원본 JSON에 보존합니다.',
             '공통 질문: 기준일 종가부터 7거래일 뒤 코스피 대비 초과수익. 매수 > +2%p, 매도 < −2%p, 보류는 그 사이입니다.',
             '중재자 내용도 개발용 품질 검토 목적으로 포함합니다. 서비스의 사용자 판정·봉인 상태는 변경하지 않았습니다.', '',
             '검토 방법: 각 토론의 자연스러움/근거 타당성을 1~5점으로 평가하거나, 고칠 문장과 이유를 알려 주세요.', '']
    stages = {'opening': '첫 주장', 'rebuttal': '반박', 'closing': '최종 정리'}
    for record in records:
        snap = Snapshot.model_validate_json((directory / record['snapshot_file']).read_text(encoding='utf-8'))
        events = EventLog.read(directory / 'debates' / (record['run_id'] + '.jsonl')) if (directory / 'debates' / (record['run_id'] + '.jsonl')).exists() else []
        accepted = [e for e in events if e['type'] == 'statement_accepted']
        lines += [f"## 토론 {record['index']} · {snap.name} · 주가 기준 {snap.as_of}", '',
                  f"- 상태: {record['status']} / 승인 발언: {len(accepted)}/6",
                  f"- 자료 수집 시각: {snap.created_at.isoformat()}",
                  f"- 스냅샷: `{snap.snapshot_id}` / 공급자: {snap.provider}",
                  f"- 소요 시간: {record.get('elapsed_seconds')}초 / 비용 장부: ${record.get('usage', {}).get('cost_usd', '미확인')}",
                  f"- 실행 ID: `{record['run_id']}`", '']
        for event in sorted(accepted, key=lambda e: (list(stages).index(e['round']), e['side'] != 'bull')):
            s = event['statement']
            side = '매수' if event['side'] == 'bull' else '매도'
            lines += [f"### {stages[event['round']]} · {side}", '', s['argument'] or s['claim'], '', '**연결 자료**', '']
            for e in s['evidence']:
                lines.append(f"- [{e['ref']}] `{e['source_id']}`: {snap.facts[e['source_id']].label}")
            lines.append('')
        result = record.get('result')
        if result:
            v = result['verdict']
            lines += ['### 중재자 — 모델 원문', '',
                      f"판정: {v['decision']} / 모델 표시 확신도: {v['confidence']} (보정된 적중 확률 아님)", '', v['reasoning'], '']
            for side, s in v['scores'].items():
                lines.append(f"- {'매수' if side == 'bull' else '매도'} 평가: {s['comment']}")
            lines += ['', '**중재자의 쟁점·한계·발언별 검토 — 모델 원문**', '', '```json', json.dumps(v.get('analysis'), ensure_ascii=False, indent=2), '```', '']
        else:
            lines += [f"중재 결과 없음. 실패 유형: {record.get('error_type', '미확인')}", '']
        used = {e['source_id'] for event in accepted for e in event['statement']['evidence']}
        if result:
            used.update(result['verdict']['decisive_evidence'])
        lines += ['### 인용 자료 대조', '']
        for key in sorted(used):
            fact = snap.facts[key]
            lines += [f"**{key} · {fact.label}**", '',
                      f"값: {fact.value} {fact.unit} / 기준일: {fact.as_of} / 출처: {fact.source}", '']
            if fact.published_at:
                lines += [f'게시 시각: {fact.published_at.isoformat()}', '']
            if fact.note:
                lines += [fact.note, '']
            if fact.url:
                lines += [f'[원자료 링크]({fact.url})', '']
        lines += ['검토: 자연스러움 __/5 · 근거 타당성 __/5 · 수정 의견:', '']
    (directory / 'review.md').write_text('\n'.join(lines), encoding='utf-8')


def export_review(directory, destination, *, index_offset=0):
    """Create readable per-debate copies, leaving original text and audit intact."""
    import re
    records = json.loads((directory / 'results.json').read_text(encoding='utf-8'))
    # Delivery numbering only; immutable run IDs and raw results are preserved.
    records = [{**record, 'index': record['index'] + index_offset} for record in records]
    render(directory, records)
    text = (directory / 'review.md').read_text(encoding='utf-8')
    chunks = re.split(r'(?m)(?=^## 토론 \d+ ·)', text)
    destination.mkdir(parents=True, exist_ok=True)
    header = chunks[0]
    for record, chunk in zip(records, chunks[1:]):
        # Machine-readable mediator analysis stays in the full review and JSON.
        compact = re.sub(r'\*\*중재자의 쟁점·한계·발언별 검토 — 모델 원문\*\*\n\n```json\n.*?\n```\n',
                         '중재자의 전체 구조화 검토는 원본 results.json과 review.md에 보존했습니다.\n',
                         chunk, flags=re.S)
        path = destination / f"debate-{record['index']}.md"
        path.write_text(header + compact, encoding='utf-8')
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, action='append', required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-paid', action='store_true')
    parser.add_argument('--review-statements', action='store_true')
    parser.add_argument('--batch-id', default='text-quality')
    parser.add_argument('--budget-ledger', type=Path)
    parser.add_argument('--budget-id', default='text-quality-three-20261107')
    args = parser.parse_args()
    if not 1 <= len(args.snapshot) <= 3:
        parser.error('One to three snapshots required')
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', args.batch_id):
        parser.error('Invalid batch id')
    snapshots = [Snapshot.model_validate_json(p.read_text(encoding='utf-8')) for p in args.snapshot]
    if any('fixture' in s.provider.lower() for s in snapshots):
        parser.error('Expected recorded live-provider snapshots')
    load_dotenv(args.env_file)
    settings = replace(load_settings(), data_dir=args.output.resolve(), rag_enabled=False,
                       worker_budget_id=args.budget_id, worker_budget_usd='5')
    if not args.allow_paid:
        print(json.dumps({'dry_run': True, 'models': selected_models(settings),
                          'snapshots': [s.snapshot_id for s in snapshots], 'budget_usd': 5}, ensure_ascii=False))
        return
    directory = settings.data_dir
    directory.mkdir(parents=True, exist_ok=False)
    ledger_path = args.budget_ledger or directory / 'provider-budget.sqlite3'
    ledger = WorkerSpendLedger(ledger_path, settings.worker_budget_id, settings.worker_budget_usd)
    records = []
    for index, (source, snap) in enumerate(zip(args.snapshot, snapshots), 1):
        snapshot_file = f'snapshot-{index}.json'
        (directory / snapshot_file).write_bytes(source.read_bytes())
        run_id = f'{args.batch_id}-{index}-{snap.ticker}-{snap.as_of}'
        record = dict(index=index, run_id=run_id, snapshot_file=snapshot_file,
                      source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), status='running')
        records.append(record)
        save(directory / 'results.json', records)
        audit = RunAudit(directory, run_id, ticker=snap.ticker, data_date=str(snap.as_of),
                         max_extra_rounds=0, models=selected_models(settings),
                         efforts={'debater': settings.debater_effort, 'moderator': settings.moderator_effort})
        audit.attach_snapshot(snap)
        audit.attach_context(None, retrieval_config={'enabled': False})
        audit.data['config']['review_statements'] = args.review_statements
        runner = LiveRunner(settings, budget=ledger, review_statements=args.review_statements)
        runner.audit = audit
        audit.attach_runner(runner)
        start = time.perf_counter()
        def emit(event, payload):
            audit.observe_event(event, payload)
            if event in ('statement_accepted', 'moderator_started'):
                print(json.dumps({'index': index, 'event': event, 'side': payload.get('side'),
                                  'round': payload.get('round')}, ensure_ascii=False), flush=True)
        try:
            record['result'] = runner.run(snap, run_id, 0, emit)
            record['status'] = 'completed'
            audit.finish('completed', usage=runner.usage(), result=record['result'])
        except Exception as exc:
            record.update(status='failed', error_type=type(exc).__name__)
            audit.finish('failed', usage=runner.usage(), error=exc)
        finally:
            record['usage'] = runner.usage()
            record['usage_complete'] = runner.usage_complete
            record['elapsed_seconds'] = round(time.perf_counter() - start, 3)
            runner.close()
            save(directory / 'results.json', records)
            save(directory / 'budget-summary.json', ledger.summary())
            render(directory, records)
        print(json.dumps({'index': index, 'status': record['status'], 'usage': record['usage']}, ensure_ascii=False), flush=True)
        if ledger.summary()['halted'] or not record['usage_complete']:
            break


if __name__ == '__main__':
    main()
