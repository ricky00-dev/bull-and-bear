import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { ReturnChart } from '../components/ReturnChart'
import { BandBar } from '../components/ScoreBits'
import { Card, ErrorNotice, Screen, Skeleton, TopBar } from '../components/ui'
import { api } from '../lib/api'
import { monthDay, pct, pctPoint, won } from '../lib/format'
import { describe } from '../lib/glossary'
import { headlineScore } from '../lib/score'
import type { ScoreView } from '../lib/types'
import { DECISION_LABEL } from '../lib/types'

/** 채점 결과. 숫자보다 "왜 맞았나·틀렸나"를 돌아보게 하는 화면. */
export function ScorePage() {
  const { id = '' } = useParams()
  const q = useQuery({ queryKey: ['me', 'judgment', id], queryFn: () => api.myJudgment(id) })
  const debateId = q.data?.judgment.debateId
  const chart = useQuery({ queryKey: ['chart', debateId], queryFn: () => api.chart(debateId!), enabled: !!debateId })

  if (q.isError) {
    return (
      <Screen>
        <TopBar title="채점 결과" back="/me" />
        <ErrorNotice message="채점 결과를 불러오지 못했어요" onRetry={() => q.refetch()} />
      </Screen>
    )
  }
  if (!q.data) {
    return (
      <Screen>
        <TopBar title="채점 결과" back="/me" />
        <div className="flex flex-col gap-3 px-5">
          <Skeleton className="h-10 w-56" />
          <Skeleton className="h-40 w-full" />
        </div>
      </Screen>
    )
  }

  const { judgment: j, evidencePicks, memo, decisiveEvidence, holdBand } = q.data
  const latest = headlineScore(j)
  const final = j.scores.find((s) => s.horizonDays === 7)
  const nextPending = j.scores.find((s) => s.status === 'PENDING')

  const headline = !latest
    ? `채점을 기다리는 중이에요`
    : latest.userHit
      ? latest.horizonDays === 7 ? '적중했어요' : '3거래일까지는 맞고 있어요'
      : latest.horizonDays === 7 ? '이번엔 빗나갔어요' : '3거래일까지는 빗나가고 있어요'

  return (
    <Screen>
      <TopBar title={j.stockName} sub={`${monthDay(j.tradeDate)} 판정 · 기준가 ${won(j.basePrice)}`} back="/me" />
      <main className="flex flex-1 flex-col gap-3.5 px-5 pb-8 pt-1">
        <div className="flex flex-col gap-1">
          <p className="text-[13px] text-sub">
            {latest ? `${monthDay(latest.scoredTradeDate!)} · 판정 ${latest.horizonDays}거래일 뒤` : `첫 채점 ${monthDay(nextPending!.scheduledDate)} 예정`}
          </p>
          <h2 className="text-2xl font-extrabold tracking-tight">{headline}</h2>
        </div>

        {latest && <ResultCard s={latest} band={holdBand} />}

        <Card className="flex flex-col gap-2.5">
          <h3 className="text-sm font-extrabold">판정 뒤 주가는 이렇게 움직였어요</h3>
          {chart.data ? <ReturnChart chart={chart.data} /> : <Skeleton className="h-44 w-full" />}
        </Card>

        <div className="grid grid-cols-2 gap-2.5">
          <Card className="flex flex-col gap-1">
            <span className="text-xs text-sub">나 · {DECISION_LABEL[j.decision]}</span>
            <span className="text-lg font-extrabold">{hitLabel(final, 'user')}</span>
            <span className="text-[11px] text-sub">확신 {j.confidence}%</span>
          </Card>
          <Card className="flex flex-col gap-1 border-mod-line bg-mod-soft">
            <span className="text-xs text-mod">AI · {DECISION_LABEL[j.moderatorDecision]}</span>
            <span className="text-lg font-extrabold">{hitLabel(final, 'moderator')}</span>
            <span className="text-[11px] text-mod">7거래일 기준</span>
          </Card>
        </div>

        <Card className="flex flex-col gap-3">
          <h3 className="text-sm font-extrabold">복기</h3>
          <EvidenceRow title="내가 설득력 있다고 고른 근거" ids={evidencePicks} empty="고른 근거가 없어요" />
          <EvidenceRow title="중재자가 결정적이라 본 근거" ids={decisiveEvidence} empty="-" />
          {memo && (
            <p className="rounded-xl bg-ground px-3.5 py-3 text-sm leading-relaxed">
              <span className="font-bold">그때 내 메모 · </span>
              {memo}
            </p>
          )}
          <Link to={`/debates/${j.debateId}`} className="text-center text-sm font-bold text-down underline-offset-2 hover:underline">
            토론 다시 보기
          </Link>
        </Card>

        <p className="text-[11px] leading-relaxed text-sub">
          코스피 대비 초과수익으로 채점해요. 매수는 +{holdBand}%p 초과, 매도는 −{holdBand}%p 미만, 보류는 ±{holdBand}%p 이내면
          적중이에요.
        </p>
      </main>
    </Screen>
  )
}

function ResultCard({ s, band }: { s: ScoreView; band: number }) {
  return (
    <Card className="flex flex-col gap-4">
      <div className="grid grid-cols-3 gap-2 text-center">
        <Num label="종목" value={pct(s.stockReturn!)} />
        <Num label="코스피" value={pct(s.indexReturn!)} />
        <Num label="초과수익" value={pctPoint(s.excessReturn!)} strong />
      </div>
      <BandBar excess={s.excessReturn!} band={band} />
    </Card>
  )
}

function Num({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-sub">{label}</span>
      <span className={`text-lg ${strong ? 'font-extrabold' : 'font-bold'}`}>{value}</span>
    </div>
  )
}

function EvidenceRow({ title, ids, empty }: { title: string; ids: string[]; empty: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-xs text-sub">{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {ids.length === 0 && <span className="text-[13px] text-sub">{empty}</span>}
        {ids.map((id) => (
          <span key={id} className="rounded-lg bg-ground px-2.5 py-1.5 text-xs font-bold">
            {describe(id).label}
          </span>
        ))}
      </div>
    </div>
  )
}

function hitLabel(s: ScoreView | undefined, who: 'user' | 'moderator') {
  if (!s || s.status === 'PENDING') return s ? `${monthDay(s.scheduledDate)} 채점` : '-'
  const hit = who === 'user' ? s.userHit : s.moderatorHit
  return hit ? '적중' : '빗나감'
}
