import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { EvidenceSheet } from '../components/EvidenceSheet'
import { DebatePreparation } from '../components/DebatePreparation'
import { RagPanel } from '../components/RagPanel'
import { StatementBubble } from '../components/StatementBubble'
import { BottomBar, Icon, PrimaryButton, Screen, TopBar } from '../components/ui'
import { ICONS } from '../components/icons'
import { api } from '../lib/api'
import { evidenceCitations, MAX_EVIDENCE_PICKS, pairStatements, previousOpponent } from '../lib/evidence'
import { useEvidencePicks } from '../lib/useEvidencePicks'
import type { Evidence, Round } from '../lib/types'
import { ROUND_LABEL } from '../lib/types'
import { type AcceptedStatement, useDebateStream } from '../lib/useDebateStream'

const ROUNDS: Round[] = ['opening', 'rebuttal', 'closing']

export function DebatePage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const debate = useQuery({ queryKey: ['debate', id], queryFn: () => api.debate(id) })
  const stream = useDebateStream(id)
  const { picks, toggle } = useEvidencePicks(id)
  const [sheet, setSheet] = useState<Evidence | null>(null)
  const [followingOverride, setFollowing] = useState<boolean | null>(null)
  const following = followingOverride ?? debate.data?.status === 'RUNNING'
  const endRef = useRef<HTMLDivElement>(null)
  const followRef = useRef<boolean | null>(null)

  const done = stream.phase === 'sealed'
  // 이미 판정한 토론이면 결과로 바로 갈 수 있게
  const reveal = useQuery({ queryKey: ['reveal', id], queryFn: () => api.reveal(id), enabled: done, retry: false })

  // 이전 발언을 읽으려고 위로 올렸다면 새 발언이 와도 읽던 위치를 유지한다.
  useEffect(() => {
    let previousY = window.scrollY
    const onScroll = () => {
      const nearEnd = document.documentElement.scrollHeight - window.innerHeight - window.scrollY < 160
      if (nearEnd || window.scrollY < previousY) {
        followRef.current = nearEnd
        setFollowing(nearEnd)
      }
      previousY = window.scrollY
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const scrollToLatest = () => {
    followRef.current = true
    setFollowing(true)
    endRef.current?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'end' })
  }

  // 새 발언이 오면 따라가기. 근거 시트가 열렸거나 이전 발언을 읽을 때는 그대로.
  useEffect(() => {
    const follow = followRef.current ?? debate.data?.status === 'RUNNING'
    if (!sheet && follow) endRef.current?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'end' })
  }, [stream.statements.length, sheet, debate.data?.status])

  const d = debate.data
  const asOf = d?.tradeDate ?? stream.asOf
  const sub = asOf ? `스냅샷 ${asOf.slice(5).replace('-', '/')} 종가 기준 · 데이터 고정됨` : '데이터를 고정하는 중'

  return (
    <Screen wide>
      <TopBar title={d?.stockName ?? '토론'} sub={sub} back={d ? `/stocks/${d.ticker}` : '/'} />

      <div className="sticky top-[var(--topbar-height)] z-10 flex flex-col gap-2.5 bg-ground px-5 pb-2.5">
        <RoundProgress statements={stream.statements} current={stream.currentRound} done={done} />
        <div className="flex min-h-9 items-center gap-2 rounded-xl border border-line bg-white px-3 text-[13px]" aria-live="polite">
          <span className={`size-2 shrink-0 rounded-full ${done ? 'bg-ok' : stream.phase === 'failed' ? 'bg-faint' : 'animate-pulse-dot bg-up'}`} />
          <span className="py-2 leading-relaxed">{stream.phase === 'failed' ? stream.error : stream.activity}</span>
        </div>
      </div>

      <main className="flex flex-1 flex-col gap-3.5 px-4 pb-4 pt-1">
        <DebatePreparation state={{...stream,asOf:asOf ?? null}} onReconnect={stream.reconnect} />
        <div className="flex flex-col gap-1 py-3">
          <h2 className="text-lg font-bold">같은 자료, 두 가지 해석</h2>
          <p className="text-[13px] leading-relaxed text-sub">기준일 종가부터 7거래일 뒤 코스피 대비 수익률을 예상해요. +2%p 초과는 매수, −2%p 미만은 매도, 그 사이는 보류예요.</p>
          <p className="text-[13px] leading-relaxed text-sub">같은 라운드의 매수·매도 주장을 비교해 보세요. 설득력 있는 근거는 {MAX_EVIDENCE_PICKS}개까지 담아 판정할 때 다시 볼 수 있어요.</p>
        </div>
        {d && <RagPanel key={id} debateId={id} stockName={d.stockName} asOf={asOf} />}
        {stream.extraQuestion && (
          <div className="rounded-2xl border border-mod-line bg-mod-soft px-4 py-3 text-sm text-mod-ink">
            <span className="font-bold">중재자의 추가 질문 · </span>
            {stream.extraQuestion}
          </div>
        )}
        {pairStatements(stream.statements).map(pair => (
          <section key={pair.key} aria-label={`${ROUND_LABEL[pair.round]} 비교${pair.index ? ` ${pair.index + 1}` : ''}`} className="flex flex-col gap-3 py-3">
            <h3 className="text-base font-bold">{ROUND_LABEL[pair.round]}{pair.index > 0 ? ` ${pair.index + 1}` : ''}</h3>
            <div className="grid items-stretch gap-5 lg:grid-cols-2">
              {(['bull', 'bear'] as const).map(side => {
                const s = pair[side]
                const previous = s ? previousOpponent(s, stream.statements) : undefined
                return s ? <div id={`turn-${s.seq}`} key={s.seq} className="min-w-0 scroll-mt-[calc(var(--topbar-height)+100px)]">
                  <StatementBubble s={s} comparison onChip={setSheet} selected={picks} onPick={toggle} previousId={previous?.seq} />
                </div> : <div key={side} className="flex min-h-36 flex-col justify-center gap-2 rounded-panel border border-dashed border-line p-4 text-sm text-sub"><span className="font-bold">{side === 'bull' ? '매수 측' : '매도 측'}</span><p>{done || stream.phase === 'failed' ? '이 라운드의 발언이 전달되지 않았어요.' : '발언을 기다리고 있어요.'}</p></div>
              })}
            </div>
          </section>
        ))}
        {stream.statements.length === 0 && stream.phase !== 'failed' && (
          <p className="py-10 text-center text-sm text-sub">첫 발언을 준비하고 있어요</p>
        )}
        <div ref={endRef} />
      </main>

      <BottomBar>
        <div className="flex min-h-touch items-center justify-between gap-2">
          <p aria-live="polite" className="text-[13px] font-medium">담은 근거 {picks.length}/{MAX_EVIDENCE_PICKS}</p>
          {!following && stream.statements.length > 0 && <button type="button" onClick={scrollToLatest} className="pressable min-h-touch rounded-control px-3 text-[13px] font-bold">{done ? '마지막 발언으로 이동' : '최근 발언으로 이동'}</button>}
        </div>
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

      {sheet && <EvidenceSheet evidence={sheet} citations={evidenceCitations(stream.statements, sheet.source_id)} debateId={id} selected={picks} onPick={toggle} asOf={asOf} onClose={() => setSheet(null)} />}
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
