import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { FACT_METRICS, factReason, type FactMetric, type DocumentResult, type FactResult } from '../lib/rag'

export function RagPanel({ debateId, stockName, asOf }: { debateId: string; stockName: string; asOf: string | null }) {
  const [mode, setMode] = useState<'documents' | 'facts'>('documents')
  const [question, setQuestion] = useState('')
  const [metric, setMetric] = useState<FactMetric>('close')
  const [date, setDate] = useState('')
  const [result, setResult] = useState<DocumentResult | FactResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const sequence = useRef(0)
  useEffect(() => () => { sequence.current++ }, [])
  function clear() { setResult(null); setError(null) }
  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    clear()
    const ticket = ++sequence.current
    setBusy(true)
    try {
      const response = mode === 'documents'
        ? await api.ragSearch(debateId, question.trim())
        : await api.ragFacts(debateId, { metric, asOf: date || undefined, unit: FACT_METRICS[metric].unit })
      if (ticket === sequence.current) setResult(response)
    } catch (e) {
      if (ticket === sequence.current) setError(e instanceof Error ? e.message : '자료를 조회하지 못했습니다.')
    } finally {
      if (ticket === sequence.current) setBusy(false)
    }
  }
  return <details className="rounded-2xl border border-line bg-white p-4">
    <summary className="cursor-pointer font-bold">자료 찾아보기</summary>
    <p className="my-3 text-xs text-sub">{stockName} · {asOf ? `${asOf} 저장 자료 기준` : '자료 준비 중'}<br />조회해도 새 토론을 시작하지 않습니다.</p>
    <form onSubmit={submit} className="flex flex-col gap-3">
      <fieldset disabled={busy || !asOf} className="flex flex-col gap-3 disabled:opacity-60">
        <legend className="mb-2 text-sm font-bold">조회 방식</legend>
        <div className="flex gap-4 text-sm">
          <label><input type="radio" name={`rag-mode-${debateId}`} checked={mode === 'documents'} onChange={() => { setMode('documents'); clear() }} /> 문서 검색</label>
          <label><input type="radio" name={`rag-mode-${debateId}`} checked={mode === 'facts'} onChange={() => { setMode('facts'); clear() }} /> 수치 조회</label>
        </div>
        {mode === 'documents' ? <>
          <label className="text-sm">찾을 내용
            <input className="mt-1 w-full rounded-lg border border-line p-2" required maxLength={1000} value={question}
              onChange={e => { setQuestion(e.target.value); clear() }} placeholder="예: PER의 의미와 해석 시 주의점" />
          </label>
          <p className="text-xs text-sub">저장 시점에 연결된 자료에서 관련 문단을 찾습니다. 과거 자료를 최신 문서로 바꾸지 않습니다. 실제 수치는 ‘수치 조회’에서 확인해 주세요.</p>
        </> : <>
          <label className="text-sm">지표
            <select className="mt-1 w-full rounded-lg border border-line p-2" value={metric} onChange={e => { setMetric(e.target.value as FactMetric); clear() }}>
              {Object.entries(FACT_METRICS).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}
            </select>
          </label>
          <label className="text-sm">기준일 (선택)
            <input type="date" className="mt-1 w-full rounded-lg border border-line p-2" value={date} max={asOf ?? undefined} onChange={e => { setDate(e.target.value); clear() }} />
          </label>
          <p className="text-xs text-sub">단위: {FACT_METRICS[metric].unit} · 날짜를 비우면 저장 자료의 기준일을 사용합니다. 다른 날짜의 자료를 새로 수집하지 않습니다.</p>
        </>}
        <button className="rounded-xl bg-ink px-4 py-2 text-sm font-bold text-white disabled:opacity-50" type="submit" disabled={mode === 'documents' && !question.trim()}>
          {busy ? '조회 중…' : mode === 'documents' ? '문서 검색하기' : '수치 조회하기'}
        </button>
      </fieldset>
    </form>
    {error && <p role="alert" className="mt-3 text-sm text-down">{error}</p>}
    <div aria-live="polite" aria-busy={busy} className="mt-3 space-y-3 text-sm">
      {result && <p className="text-xs text-sub">{result.ticker} · 저장 기준일 {result.snapshot_as_of}</p>}
      {result?.mode === 'documents' && <>
        <p className="font-bold">관련 문서 · 수치 검증 결과가 아닙니다</p>
        {result.documents.length === 0 && <p>조건에 맞는 문서가 없습니다. 검색어를 바꿔 보세요.</p>}
        {result.documents.map(doc => <article key={doc.chunk_id} className="rounded-lg border border-line p-3">
          <p className="whitespace-pre-wrap">{doc.text}</p>
          <p className="mt-2 text-xs text-sub">적용 범위: {doc.applicability}</p>
          {doc.limitations.map((limit, i) => <p key={i} className="text-xs text-sub">주의: {limit}</p>)}
        </article>)}
      </>}
      {result?.mode === 'facts' && <>
        <p className="font-bold">저장 수치 조회</p>
        {result.answerability !== 'supported_fact' ? <>
          <p>검증된 수치를 제공할 수 없습니다.</p>
          {result.reasons.map(reason => <p key={reason}>{factReason(reason)}</p>)}
        </> : result.facts.map(fact => <article key={fact.fact_id} className="rounded-lg border border-line p-3">
          <p className="text-lg font-bold">{fact.value.toLocaleString('ko-KR', { maximumFractionDigits: 6 })} {fact.unit}</p>
          <p className="mt-1 text-xs text-sub">기준일 {fact.as_of} · 출처 {fact.source}</p>
          <p className="text-xs text-sub">저장 자료의 날짜·단위·입력 근거 검증을 통과한 값입니다.</p>
        </article>)}
      </>}
    </div>
  </details>
}
