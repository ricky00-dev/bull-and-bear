import { useState } from 'react'
import { monthDay, pct, pctPoint, todayKst } from '../lib/format'
import { correctDecision, preferredScore } from '../lib/score'
import type { Decision, ScoreView } from '../lib/types'
import { DECISION_LABEL } from '../lib/types'
import { Card } from './ui'
import { BandBar } from './ScoreBits'

const COLOR: Record<Decision, string> = { BUY: 'text-up-ink', HOLD: 'text-ink', SELL: 'text-down-ink' }
function hitLabel(hit: boolean | null) { return hit === null ? '결과 확인 중' : hit ? '적중' : '빗나감' }

/** 같은 기간의 내 판정·AI 판정·실제 결과를 함께 읽는다. 다른 기간의 적중 여부를 섞지 않는다. */
export function JudgmentComparison({ mine, moderator, scores, holdBand, loading = false, error, onRetry }: {
  mine: Decision; moderator: Decision; scores: ScoreView[]; holdBand?: number
  loading?: boolean; error?: boolean; onRetry?: () => void
}) {
  const [horizon, setHorizon] = useState<number | null>(null)
  const selected = scores.find(s => s.horizonDays === (horizon ?? preferredScore(scores)?.horizonDays ?? 7))
  const days = horizon ?? selected?.horizonDays ?? 7
  const scored = selected?.status === 'SCORED'
  const correct = scored && selected.excessReturn !== null && holdBand !== undefined ? correctDecision(selected.excessReturn, holdBand) : null
  return (
    <Card className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-bold">나 · AI · 실제 결과</h2>
        <div className="flex rounded-control bg-ground p-1" aria-label="비교할 기간">
          {[3, 7].map(n => <button key={n} type="button" aria-pressed={days === n} onClick={() => setHorizon(n)}
            className={`min-h-touch rounded-md px-3 text-sm ${days === n ? 'bg-ink font-bold text-white' : 'pressable text-sub'}`}>{n}거래일</button>)}
        </div>
      </div>
      <div className="grid grid-cols-3 divide-x divide-line">
        <div className="flex min-w-0 flex-col gap-2 pr-2">
          <p className="text-[13px] text-sub">내 판정</p>
          <p className={`text-xl font-bold ${COLOR[mine]}`}>{DECISION_LABEL[mine]}</p>
          <p className="text-[13px]">{scored ? hitLabel(selected.userHit) : error ? '미확인' : loading ? '조회 중' : '결과 대기'}</p>
        </div>
        <div className="flex min-w-0 flex-col gap-2 px-3">
          <p className="text-[13px] text-sub">AI 판정</p>
          <p className={`text-xl font-bold ${COLOR[moderator]}`}>{DECISION_LABEL[moderator]}</p>
          <p className="text-[13px]">{scored ? hitLabel(selected.moderatorHit) : error ? '미확인' : loading ? '조회 중' : '결과 대기'}</p>
        </div>
        <div className="flex min-w-0 flex-col gap-2 pl-3">
          <p className="text-[13px] text-sub">실제 결과</p>
          <p className={`text-xl font-bold ${correct ? COLOR[correct] : 'text-sub'}`}>{correct ? DECISION_LABEL[correct] : scored ? '확인 중' : error ? '미확인' : loading ? '조회 중' : '채점 전'}</p>
          <p className="text-[13px]">{scored && selected.excessReturn !== null ? pctPoint(selected.excessReturn) : `${days}거래일 뒤`}</p>
        </div>
      </div>
      {scored && selected.excessReturn !== null && holdBand !== undefined && <BandBar excess={selected.excessReturn} band={holdBand} />}
      <div aria-live="polite" className="flex flex-col gap-2 border-t border-line-soft pt-3 text-[13px] leading-relaxed text-sub">
        {loading ? <p>채점 일정을 불러오는 중이에요.</p> : error ? <div role="alert"><p>채점 상태를 불러오지 못했어요.</p><button type="button" onClick={onRetry} className="pressable min-h-touch rounded-control px-2 font-bold text-ink">다시 시도</button></div> : scored ? <>
          <p>{selected.scoredTradeDate ? monthDay(selected.scoredTradeDate) : ''} · {days}거래일 {days === 3 ? '중간 결과' : '최종 결과'} · 코스피 대비 초과수익</p>
          <div className="flex flex-wrap justify-between gap-2 text-sm"><span>종목 {selected.stockReturn === null ? '미제공' : pct(selected.stockReturn)}</span><span>코스피 {selected.indexReturn === null ? '미제공' : pct(selected.indexReturn)}</span></div>
        </> : <p>{selected ? selected.scheduledDate < todayKst() ? `${monthDay(selected.scheduledDate)} 예상일 이후 · 확정 종가를 기다리고 있어요.` : `${monthDay(selected.scheduledDate)} 예상 · 확정 종가가 들어오면 채점해요.` : '아직 채점 일정을 확인할 수 없어요.'}</p>}
        {scores.some(s => s.status === 'PENDING') && <p>{scores.filter(s => s.status === 'PENDING').toSorted((a,b) => a.horizonDays-b.horizonDays).map(s => `${s.horizonDays}거래일 ${monthDay(s.scheduledDate)} 예상`).join(' / ')}<br />예상일은 휴장·자료 수신에 따라 달라질 수 있어요.</p>}
      </div>
    </Card>
  )
}
