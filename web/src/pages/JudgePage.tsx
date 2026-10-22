import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { BottomBar, Icon, PrimaryButton, Screen, TopBar } from '../components/ui'
import { ICONS } from '../components/icons'
import { api, ApiError } from '../lib/api'
import { chipText } from '../lib/glossary'
import type { Decision } from '../lib/types'
import { useDebateStream } from '../lib/useDebateStream'

const OPTIONS: { key: Decision; label: string; sub: string; icon: string; on: string; soft: string }[] = [
  { key: 'BUY', label: '매수', sub: '코스피보다 더 오를 것 같아요', icon: ICONS.up, on: 'border-up bg-up-soft', soft: 'bg-up text-white' },
  { key: 'HOLD', label: '보류', sub: '코스피와 비슷하게 움직일 것 같아요', icon: ICONS.flat, on: 'border-ink bg-ground', soft: 'bg-ink text-white' },
  { key: 'SELL', label: '매도', sub: '코스피보다 더 내릴 것 같아요', icon: ICONS.down, on: 'border-down bg-down-soft', soft: 'bg-down text-white' },
]
const MAX_PICKS = 2

export function JudgePage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const debate = useQuery({ queryKey: ['debate', id], queryFn: () => api.debate(id) })
  const stream = useDebateStream(id) // 근거 목록용. 끝난 토론이라 바로 재생된다

  const [decision, setDecision] = useState<Decision | null>(null)
  const [confidence, setConfidence] = useState(70)
  const [picks, setPicks] = useState<string[]>([])
  const [memo, setMemo] = useState('')
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
    mutationFn: () => api.submitJudgment(id, { decision: decision!, confidence, evidencePicks: picks, memo: memo.trim() || null }),
    onSuccess: (reveal) => {
      queryClient.setQueryData(['reveal', id], reveal)
      navigate(`/debates/${id}/reveal`, { replace: true })
    },
  })

  const togglePick = (sourceId: string) =>
    setPicks((cur) => (cur.includes(sourceId) ? cur.filter((p) => p !== sourceId) : [...cur, sourceId].slice(-MAX_PICKS)))

  const onSubmit = () => {
    setTried(true)
    if (decision) submit.mutate()
  }

  const name = debate.data?.stockName ?? '이 종목'
  const error = submit.error instanceof ApiError ? submit.error.message : submit.error ? '제출하지 못했어요. 다시 시도해 주세요.' : null

  return (
    <Screen>
      <TopBar title={name} sub="내 판정" />
      <main className="flex flex-1 flex-col gap-6 px-5 pb-5 pt-1">
        <div className="flex flex-col gap-1.5">
          <h2 className="text-2xl font-extrabold leading-snug tracking-tight">7거래일 뒤, {name}은?</h2>
          <p className="text-sm leading-relaxed text-sub">
            코스피보다 2%p 넘게 오르면 매수, 2%p 넘게 내리면 매도, 그 사이면 보류가 맞아요.
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
                onClick={() => setDecision(o.key)}
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
            onChange={(e) => setConfidence(Number(e.target.value))}
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
            <p className="text-xs text-sub">내 판정 습관 리포트에 쓰여요</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {evidence.map(([sourceId, text]) => {
              const on = picks.includes(sourceId)
              return (
                <button
                  key={sourceId}
                  type="button"
                  aria-pressed={on}
                  onClick={() => togglePick(sourceId)}
                  className={`min-h-10 rounded-xl border px-3 text-[13px] font-bold ${on ? 'border-ink bg-ink text-white' : 'border-[#d5d8de] bg-white'}`}
                >
                  {text}
                </button>
              )
            })}
            {evidence.length === 0 && <p className="text-[13px] text-sub">근거를 불러오는 중…</p>}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <label htmlFor="memo" className="text-sm font-extrabold">
            한 줄 메모 <span className="font-medium text-sub">(선택)</span>
          </label>
          <input
            id="memo"
            value={memo}
            maxLength={200}
            onChange={(e) => setMemo(e.target.value)}
            placeholder="나중에 복기할 때 보여드려요"
            className="min-h-12 rounded-xl border border-[#d5d8de] bg-white px-3.5 text-[15px] outline-none focus:border-ink"
          />
        </div>
      </main>

      <BottomBar>
        {tried && !decision && <p className="text-[13px] font-bold text-up-ink">매수·보류·매도 중 하나를 골라주세요</p>}
        {error && <p className="text-[13px] font-bold text-up-ink">{error}</p>}
        <PrimaryButton disabled={submit.isPending} onClick={onSubmit}>
          {submit.isPending ? '제출하는 중…' : '제출하고 AI 판정 열기'}
        </PrimaryButton>
        <p className="text-center text-xs text-sub">제출하면 바꿀 수 없어요</p>
      </BottomBar>
    </Screen>
  )
}
