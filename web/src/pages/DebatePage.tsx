import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { EvidenceSheet } from '../components/EvidenceSheet'
import { BottomBar, Icon, PrimaryButton, Screen, TopBar } from '../components/ui'
import { ICONS } from '../components/icons'
import { api } from '../lib/api'
import { chipText } from '../lib/glossary'
import type { Evidence, Round } from '../lib/types'
import { ROUND_LABEL } from '../lib/types'
import { type AcceptedStatement, useDebateStream } from '../lib/useDebateStream'

const ROUNDS: Round[] = ['opening', 'rebuttal', 'closing']

export function DebatePage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const debate = useQuery({ queryKey: ['debate', id], queryFn: () => api.debate(id) })
  const stream = useDebateStream(id)
  const [sheet, setSheet] = useState<Evidence | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  const done = stream.phase === 'sealed'
  // 이미 판정한 토론이면 결과로 바로 갈 수 있게
  const reveal = useQuery({ queryKey: ['reveal', id], queryFn: () => api.reveal(id), enabled: done, retry: false })

  // 새 발언이 오면 아래로 (사용자가 근거 시트를 보고 있을 때는 그대로)
  useEffect(() => {
    if (!sheet) endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [stream.statements.length, sheet])

  const d = debate.data
  const asOf = d?.tradeDate ?? stream.asOf
  const sub = asOf ? `스냅샷 ${asOf.slice(5).replace('-', '/')} 종가 기준 · 데이터 고정됨` : '데이터를 고정하는 중'

  return (
    <Screen>
      <TopBar title={d?.stockName ?? '토론'} sub={sub} back={d ? `/stocks/${d.ticker}` : '/'} />

      <div className="sticky top-[68px] z-10 flex flex-col gap-2.5 bg-ground px-5 pb-2.5">
        <RoundProgress statements={stream.statements} current={stream.currentRound} done={done} />
        <div className="flex min-h-9 items-center gap-2 rounded-xl border border-line bg-white px-3 text-[13px]" aria-live="polite">
          <span className={`size-2 shrink-0 rounded-full ${done ? 'bg-ok' : stream.phase === 'failed' ? 'bg-faint' : 'animate-pulse-dot bg-up'}`} />
          <span className="truncate">{stream.phase === 'failed' ? stream.error : stream.activity}</span>
        </div>
      </div>

      <main className="flex flex-1 flex-col gap-3.5 px-4 pb-4 pt-1">
        {stream.extraQuestion && (
          <div className="rounded-2xl border border-mod-line bg-mod-soft px-4 py-3 text-sm text-mod-ink">
            <span className="font-bold">중재자의 추가 질문 · </span>
            {stream.extraQuestion}
          </div>
        )}
        {stream.statements.map((s) => (
          <Bubble key={s.seq} s={s} onChip={setSheet} />
        ))}
        {stream.statements.length === 0 && stream.phase !== 'failed' && (
          <p className="py-10 text-center text-sm text-sub">첫 발언을 준비하고 있어요</p>
        )}
        <div ref={endRef} />
      </main>

      <BottomBar>
        <p className="flex items-center gap-2 text-xs text-mod">
          <Icon d={ICONS.lock} size={14} stroke={2.2} />
          {done ? 'AI 중재자 판정 완료 · 내 판정을 내면 열려요' : '토론이 끝나면 판정할 수 있어요'}
        </p>
        {reveal.data ? (
          <PrimaryButton onClick={() => navigate(`/debates/${id}/reveal`)}>내 판정 결과 보기</PrimaryButton>
        ) : (
          <PrimaryButton disabled={!done} onClick={() => navigate(`/debates/${id}/judge`)}>
            {done ? '내 판정 내리기' : stream.phase === 'failed' ? '토론이 중단됐어요' : '토론 진행 중…'}
          </PrimaryButton>
        )}
      </BottomBar>

      {sheet && <EvidenceSheet evidence={sheet} asOf={asOf} onClose={() => setSheet(null)} />}
    </Screen>
  )
}

function RoundProgress({ statements, current, done }: { statements: AcceptedStatement[]; current: Round | null; done: boolean }) {
  const count = (r: Round) => statements.filter((s) => s.round === r).length
  return (
    <ol className="grid grid-cols-3 gap-1.5" aria-label="토론 진행">
      {ROUNDS.map((r) => {
        const complete = done || count(r) >= 2
        const active = !complete && current === r
        return (
          <li key={r} className="flex flex-col gap-1.5" aria-current={active ? 'step' : undefined}>
            <span className={`h-1 rounded-full ${complete ? 'bg-ink' : active ? 'bg-faint' : 'bg-line'}`} />
            <span className={`text-[11px] font-bold ${complete || active ? 'text-ink' : 'text-faint'}`}>{ROUND_LABEL[r]}</span>
          </li>
        )
      })}
    </ol>
  )
}

function Bubble({ s, onChip }: { s: AcceptedStatement; onChip: (e: Evidence) => void }) {
  const bull = s.side === 'bull'
  const tone = bull
    ? { badge: 'bg-up', name: 'text-up-ink', border: 'border-up-line', chip: 'border-up-line bg-up-soft', check: 'text-up-ink' }
    : { badge: 'bg-down', name: 'text-down-ink', border: 'border-down-line', chip: 'border-down-line bg-down-soft', check: 'text-down-ink' }
  const retried = s.attempts > 1

  return (
    <article className={`animate-rise flex flex-col gap-1.5 ${bull ? 'mr-9' : 'ml-9 items-end'}`}>
      <header className={`flex items-center gap-1.5 text-xs font-extrabold ${tone.name}`}>
        <span className={`rounded-md px-1.5 py-0.5 text-[11px] text-white ${tone.badge}`}>{bull ? '매수' : '매도'}</span>
        {ROUND_LABEL[s.round]}
      </header>
      <div className={`flex w-full flex-col gap-2.5 border bg-white p-3.5 ${tone.border} ${bull ? 'rounded-[4px_16px_16px_16px]' : 'rounded-[16px_4px_16px_16px]'}`}>
        <p className="text-[15px] leading-relaxed">{s.statement.claim}</p>
        <div className="flex flex-wrap gap-1.5">
          {s.statement.evidence.map((e) => (
            <button
              key={e.ref}
              type="button"
              onClick={() => onChip(e)}
              className={`flex min-h-8 items-center gap-1 rounded-lg border px-2.5 text-xs font-bold ${tone.chip}`}
            >
              {chipText(e.source_id, e.value)}
              <Icon d={ICONS.check} size={12} stroke={2.5} className={tone.check} />
            </button>
          ))}
        </div>
      </div>
      <p className={`px-1 text-[11px] ${retried ? 'text-warn' : 'text-sub'}`}>
        {retried
          ? `검증기가 ${s.attempts - 1}회 반려한 뒤 고친 발언 · 근거 ${s.statement.evidence.length}개 원본과 일치`
          : `근거 ${s.statement.evidence.length}개 · 원본과 일치`}
      </p>
    </article>
  )
}
