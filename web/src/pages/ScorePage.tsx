import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { ReturnChart } from '../components/ReturnChart'
import { BandBar } from '../components/ScoreBits'
import { Card, ErrorNotice, Screen, Skeleton, TopBar } from '../components/ui'
import { api } from '../lib/api'
import { dueLabel, monthDay, pct, pctPoint, won } from '../lib/format'
import { describe } from '../lib/glossary'
import { headlineScore } from '../lib/score'
import type { PickOutcome, PickResult, ScoreView } from '../lib/types'
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

  const { judgment: j, memo, decisiveEvidence, holdBand, pickResults, pickHorizon } = q.data
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
            {latest ? `${monthDay(latest.scoredTradeDate!)} · 판정 ${latest.horizonDays}거래일 뒤` : `첫 ${dueLabel(nextPending!.scheduledDate)}`}
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
          <PickResults picks={pickResults} horizon={pickHorizon} userHit={latest?.userHit ?? null} />
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

const SIDE_LABEL = { bull: '매수 측', bear: '매도 측' } as const

const OUTCOME: Record<PickOutcome, { text: string; cls: string }> = {
  RIGHT: { text: '맞은 근거', cls: 'bg-ok text-white' },
  WRONG: { text: '빗나간 근거', cls: 'bg-line text-sub' },
  FLAT: { text: '판가름 안 남', cls: 'bg-ground text-sub' },
  PENDING: { text: '채점 전', cls: 'bg-ground text-sub' },
  UNKNOWN: { text: '-', cls: 'bg-ground text-sub' },
}

/**
 * 내 근거 채점. 근거는 그걸 인용한 쪽(매수 측·매도 측)의 방향을 따른다.
 * 판정이 틀려도 근거 보는 눈은 맞았을 수 있고, 그 반대도 있다는 걸 보여주는 게 목적.
 */
function PickResults({ picks, horizon, userHit }: { picks: PickResult[]; horizon: number | null; userHit: boolean | null }) {
  const graded = picks.filter((p) => p.result === 'RIGHT' || p.result === 'WRONG')
  const right = graded.filter((p) => p.result === 'RIGHT').length
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <p className="text-xs text-sub">내가 설득력 있다고 고른 근거</p>
        {graded.length > 0 && (
          <span className="text-xs font-bold">
            {graded.length}개 중 {right}개 맞음{horizon === 3 && <span className="font-medium text-sub"> · 3거래일 중간</span>}
          </span>
        )}
      </div>
      {picks.length === 0 && <span className="text-[13px] text-sub">고른 근거가 없어요</span>}
      <ul className="flex flex-col gap-1.5">
        {picks.map((p) => (
          <li key={p.sourceId} className="flex items-center justify-between gap-2 rounded-xl bg-ground px-3 py-2.5">
            <span className="flex min-w-0 flex-col">
              <span className="text-[13px] font-bold">{describe(p.sourceId).label}</span>
              <span className="text-[11px] text-sub">
                {p.sides.length === 0 ? '토론에서 인용되지 않음' : `${p.sides.map((x) => SIDE_LABEL[x]).join('·')}이 인용`}
              </span>
            </span>
            {p.result !== 'UNKNOWN' && (
              <span className={`shrink-0 rounded-md px-2 py-1 text-[11px] font-bold ${OUTCOME[p.result].cls}`}>
                {OUTCOME[p.result].text}
              </span>
            )}
          </li>
        ))}
      </ul>
      {userHit === false && right > 0 && (
        <p className="rounded-xl bg-mod-soft px-3 py-2.5 text-[13px] leading-relaxed text-mod">
          판정은 빗나갔지만 맞는 방향의 근거를 골랐어요. 그 근거를 더 무겁게 봤다면 결과가 달랐을 거예요.
        </p>
      )}
      {userHit === true && graded.length > 0 && right === 0 && (
        <p className="rounded-xl bg-ground px-3 py-2.5 text-[13px] leading-relaxed">
          판정은 맞았지만 고른 근거는 반대쪽이었어요. 이번엔 운이 따랐을 수도 있어요.
        </p>
      )}
      {picks.some((p) => p.result === 'FLAT') && (
        <p className="text-[11px] leading-relaxed text-sub">코스피와 비슷하게 움직여서 어느 쪽 근거도 결정적이지 않았어요.</p>
      )}
      {picks.some((p) => p.sides.length === 2 && (p.result === 'RIGHT' || p.result === 'WRONG')) && (
        <p className="text-[11px] leading-relaxed text-sub">양쪽이 다 인용한 근거는 같은 숫자를 다르게 해석한 거예요. 이긴 쪽 해석 기준으로 채점했어요.</p>
      )}
    </div>
  )
}

function hitLabel(s: ScoreView | undefined, who: 'user' | 'moderator') {
  if (!s || s.status === 'PENDING') return s ? dueLabel(s.scheduledDate).replace(' 예정', '') : '-'
  const hit = who === 'user' ? s.userHit : s.moderatorHit
  return hit ? '적중' : '빗나감'
}
