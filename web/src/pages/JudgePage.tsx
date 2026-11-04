import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { BottomBar, Icon, PrimaryButton, Screen, TopBar } from '../components/ui'
import { ICONS } from '../components/icons'
import { api, ApiError } from '../lib/api'
import { chipText } from '../lib/glossary'
import type { Decision } from '../lib/types'
import { useDebateStream } from '../lib/useDebateStream'
import { useEvidencePicks } from '../lib/useEvidencePicks'
import { evidenceCitations, MAX_EVIDENCE_PICKS } from '../lib/evidence'
import { EvidenceSheet } from '../components/EvidenceSheet'
import { useJudgmentDraft } from '../lib/useJudgmentDraft'

const OPTIONS: { key: Decision; label: string; sub: string; icon: string; on: string; soft: string }[] = [
  { key: 'BUY', label: '매수', sub: '코스피보다 더 오를 것 같아요', icon: ICONS.up, on: 'border-up bg-up-soft', soft: 'bg-up text-white' },
  { key: 'HOLD', label: '보류', sub: '코스피와 비슷하게 움직일 것 같아요', icon: ICONS.flat, on: 'border-ink bg-ground', soft: 'bg-ink text-white' },
  { key: 'SELL', label: '매도', sub: '코스피보다 더 내릴 것 같아요', icon: ICONS.down, on: 'border-down bg-down-soft', soft: 'bg-down text-white' },
]
const MAX_PICKS = MAX_EVIDENCE_PICKS

export function JudgePage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const debate = useQuery({ queryKey: ['debate', id], queryFn: () => api.debate(id) })
  const stream = useDebateStream(id) // 근거 목록용. 끝난 토론이라 바로 재생된다

  const form = useJudgmentDraft(id)
  const {decision, confidence, memo} = form.draft
  const { picks, toggle: togglePick, clear: clearPicks } = useEvidencePicks(id)
  const [sourceId, setSourceId] = useState<string | null>(null)
  const [tried, setTried] = useState(false)

  // 토론에 나온 근거, 같은 지표는 한 번만
  const evidence = useMemo(() => {
    const seen = new Map<string, string>()
    for (const s of stream.statements) {
      for (const e of s.statement.evidence) {
        if (!seen.has(e.source_id)) seen.set(e.source_id, chipText(e.source_id, e.value))
      }
    }
    return [...seen.entries()]
  }, [stream.statements])

  const submit = useMutation({
    mutationFn: () => api.submitJudgment(id, { decision: decision!, confidence, evidencePicks: picks.filter(p => evidence.some(([sourceId]) => sourceId === p)), memo: memo.trim() || null }),
    onSuccess: (reveal) => {
      queryClient.setQueryData(['reveal', id], reveal)
      clearPicks()
      form.clear()
      queryClient.invalidateQueries({ queryKey: ['me'] })
      navigate(`/debates/${id}/reveal`, { replace: true })
    },
  })

  const onSubmit = () => {
    setTried(true)
    if (decision) submit.mutate()
  }

  const name = debate.data?.stockName ?? '이 종목'
  const error = submit.error instanceof ApiError ? submit.error.message : submit.error ? '제출하지 못했어요. 다시 시도해 주세요.' : null

  return (
    <Screen>
      <TopBar title={name} sub="내 판정" back={`/debates/${id}`} />
      <main className="flex flex-1 flex-col gap-6 px-5 pb-5 pt-1">
        <div className="flex flex-col gap-1.5">
          <h2 className="text-2xl font-extrabold leading-snug tracking-tight">7거래일 뒤, 어떻게 움직일까요?</h2>
          <p className="text-sm leading-relaxed text-sub">
            코스피보다 2%p 넘게 오르면 매수, 2%p 넘게 내리면 매도, 그 사이면 보류가 맞아요.
          </p>
          <p className="mt-1 rounded-xl bg-ground px-3.5 py-2.5 text-[13px] leading-relaxed">
            <span className="font-bold">판정 팁 · </span>
            누가 말을 잘했는지보다 <b>어느 쪽 근거가 더 탄탄했는지</b> 떠올려 보세요. 상대의 반박에 제대로 답했는지도 중요해요.
          </p>
        </div>

        <fieldset className="flex flex-col gap-2.5">
          <legend className="sr-only">판정</legend>
          {OPTIONS.map((o) => {
            const on = decision === o.key
            return (
              <button
                key={o.key}
                type="button"
                aria-pressed={on}
                onClick={() => form.update({decision:o.key})}
                className={`flex min-h-18 items-center gap-3.5 rounded-2xl border-2 px-3.5 py-3 text-left transition-colors ${on ? o.on : 'border-line bg-white'}`}
              >
                <span className={`flex size-10 items-center justify-center rounded-xl ${on ? o.soft : 'bg-ground text-sub'}`}>
                  <Icon d={o.icon} size={22} stroke={2.4} />
                </span>
                <span className="flex flex-col gap-0.5">
                  <span className="text-[17px] font-extrabold">{o.label}</span>
                  <span className="text-[13px] text-sub">{o.sub}</span>
                </span>
              </button>
            )
          })}
        </fieldset>

        <div className="flex flex-col gap-2.5">
          <div className="flex items-baseline justify-between">
            <label htmlFor="conf" className="text-sm font-extrabold">
              얼마나 확신하나요?
            </label>
            <span className="text-xl font-extrabold">{confidence}%</span>
          </div>
          <input
            id="conf"
            type="range"
            min={50}
            max={100}
            step={10}
            value={confidence}
            onChange={(e) => form.update({confidence:Number(e.target.value)})}
            className="h-8 w-full accent-ink"
          />
          <div className="flex justify-between text-[11px] text-sub">
            <span>반반이에요</span>
            <span>확실해요</span>
          </div>
        </div>

        <div className="flex flex-col gap-2.5">
          <div className="flex flex-col gap-0.5">
            <h3 className="text-sm font-extrabold">가장 설득력 있던 근거 (최대 {MAX_PICKS}개)</h3>
            <p className="text-[13px] leading-relaxed text-sub">토론에서 담은 근거가 이어져요. 확인하거나 바꾼 뒤 제출해 주세요.</p>
          </div>
          <div className="flex items-center justify-between text-[13px]"><span>선택 {picks.length}/{MAX_PICKS}{picks.length === MAX_PICKS ? ' · 바꾸려면 먼저 해제해 주세요' : ''}</span>{picks.length > 0 && <button type="button" onClick={clearPicks} className="pressable min-h-touch rounded-control px-2 text-sub">선택 초기화</button>}</div>
          <div className="flex flex-col gap-2">
            {evidence.map(([sourceId, text]) => {
              const on = picks.includes(sourceId)
              return (<div key={sourceId} className="flex gap-2">
                <button
                  type="button"
                  aria-pressed={on}
                  disabled={!on && picks.length >= MAX_PICKS}
                  onClick={() => togglePick(sourceId)}
                  className={`min-h-touch min-w-0 flex-1 rounded-control border px-3 py-2 text-left text-[13px] font-bold transition-colors ${on ? 'border-ink bg-ink text-white' : 'pressable border-line bg-white disabled:text-faint'}`}
                >
                  {text}
                </button>
                <button type="button" aria-label={`${text} 근거 확인`} onClick={() => setSourceId(sourceId)} className="pressable min-h-touch shrink-0 rounded-control border border-line px-3 text-[13px]">확인</button>
                </div>
              )
            })}
            {evidence.length === 0 && <p className="text-[13px] text-sub">근거를 불러오는 중…</p>}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <label htmlFor="memo" className="text-sm font-extrabold">
            판정 메모 <span className="font-medium text-sub">(선택)</span>
          </label>
          <textarea
            id="memo"
            rows={3}
            value={memo}
            maxLength={200}
            onChange={(e) => form.update({memo:e.target.value})}
            aria-describedby="memo-hint"
            placeholder="나중에 복기할 때 보여드려요"
            className="min-h-28 resize-y scroll-mt-24 rounded-control border border-line bg-white px-3.5 py-3 text-base leading-relaxed outline-none focus:border-ink focus:ring-1 focus:ring-ink"
          />
          <div id="memo-hint" className="flex justify-between gap-3 text-xs text-sub"><span>{form.hasDraft ? form.saved ? '판정과 메모를 이 탭에 임시 보관했어요.' : '임시 저장을 사용할 수 없어요. 화면을 나가기 전에 입력을 확인해 주세요.' : '입력 내용은 이 탭에만 임시 보관해요.'}</span><span className="shrink-0">{memo.length}/200</span></div>
        </div>
      </main>

      <BottomBar>
        {stream.connection === 'failed' && <div role="alert" className="flex items-center justify-between gap-2 text-[13px]"><span>토론 근거에 연결하지 못했어요.</span><button type="button" onClick={stream.reconnect} className="pressable min-h-touch rounded-control px-3 font-bold">다시 연결</button></div>}
        {stream.phase === 'failed' && <p role="alert" className="text-[13px] text-sub">토론 근거를 불러오지 못했어요. 토론으로 돌아가 다시 확인해 주세요.</p>}
        {tried && !decision && <p className="text-[13px] font-bold text-up-ink">매수·보류·매도 중 하나를 골라주세요</p>}
        {error && <p className="text-[13px] font-bold text-up-ink">{error}</p>}
        <PrimaryButton disabled={submit.isPending || stream.phase !== 'sealed'} onClick={onSubmit}>
          {submit.isPending ? '제출하는 중…' : stream.phase !== 'sealed' ? '토론 근거 확인 중…' : '제출하고 AI 판정 열기'}
        </PrimaryButton>
        <p className="text-center text-xs text-sub">제출하면 바꿀 수 없어요</p>
      </BottomBar>
      {sourceId && <EvidenceSheet sourceId={sourceId} evidence={evidenceCitations(stream.statements, sourceId)[0]?.evidence} citations={evidenceCitations(stream.statements, sourceId)} asOf={debate.data?.tradeDate} debateId={id} selected={picks} onPick={togglePick} onClose={() => setSourceId(null)} />}
    </Screen>
  )
}
