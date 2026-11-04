import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { ReturnChart } from '../components/ReturnChart'
import { JudgmentComparison } from '../components/JudgmentComparison'
import { EvidenceComparison } from '../components/EvidenceComparison'
import { useDebateStream } from '../lib/useDebateStream'
import { Card, ErrorNotice, Screen, Skeleton, TopBar } from '../components/ui'
import { api } from '../lib/api'
import { monthDay, won } from '../lib/format'
import { describe } from '../lib/glossary'
import { headlineScore } from '../lib/score'
import type { PickOutcome, PickResult } from '../lib/types'

/** 채점 결과. 숫자보다 "왜 맞았나·틀렸나"를 돌아보게 하는 화면. */
export function ScorePage() {
  const { id = '' } = useParams()
  const q = useQuery({ queryKey: ['me', 'judgment', id], queryFn: () => api.myJudgment(id) })
  const debateId = q.data?.judgment.debateId
  const stream = useDebateStream(debateId)
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
  const pickScore = j.scores.find(s => s.horizonDays === pickHorizon)

  return (
    <Screen wide>
      <TopBar title={j.stockName} sub={`${monthDay(j.tradeDate)} 판정 · 기준가 ${won(j.basePrice)}`} back="/me" />
      <main className="flex flex-1 flex-col gap-3.5 px-5 pb-8 pt-1">
        <div className="flex flex-col gap-1">
          <p className="text-[13px] text-sub">{latest ? `${latest.horizonDays}거래일 ${latest.horizonDays === 3 ? '중간' : '최종'} 채점 완료` : '채점 대기 · 예상일을 확인해 주세요'}</p>
          <h2 className="text-2xl font-bold tracking-tight">내 판정을 돌아보세요</h2>
        </div>
        <JudgmentComparison mine={j.decision} moderator={j.moderatorDecision} scores={j.scores} holdBand={holdBand} />
        <EvidenceComparison mine={q.data.evidencePicks} decisive={decisiveEvidence} turns={stream.statements} asOf={j.tradeDate} debateId={j.debateId} memo={memo} />

        <Card className="flex flex-col gap-2.5">
          <h3 className="text-sm font-extrabold">판정 뒤 주가는 이렇게 움직였어요</h3>
          {chart.data ? <div className="mx-auto w-full max-w-[640px]"><ReturnChart chart={chart.data} /></div> : chart.isError ? <ErrorNotice message="수익률 차트를 불러오지 못했어요" onRetry={() => chart.refetch()} /> : <Skeleton className="h-44 w-full" />}
        </Card>

        <Card className="flex flex-col gap-3">
          <h3 className="text-base font-bold">고른 근거와 이후 주가 방향</h3>
          <p className="text-[13px] leading-relaxed text-sub">근거를 인용한 쪽과 이후 주가 방향을 비교해요. 개별 근거가 주가를 움직였다는 뜻은 아니에요.</p>
          <PickResults picks={pickResults} horizon={pickHorizon} userHit={pickScore?.userHit ?? null} />
          <Link to={`/debates/${j.debateId}`} className="pressable flex min-h-touch items-center justify-center rounded-control border border-line text-sm font-bold">토론 다시 보기</Link>
        </Card>

        <p className="text-[11px] leading-relaxed text-sub">
          코스피 대비 초과수익으로 채점해요. 매수는 +{holdBand}%p 초과, 매도는 −{holdBand}%p 미만, 보류는 ±{holdBand}%p 이내면
          적중이에요.
        </p>
      </main>
    </Screen>
  )
}

const SIDE_LABEL = { bull: '매수 측', bear: '매도 측' } as const

const OUTCOME: Record<PickOutcome, { text: string; cls: string }> = {
  RIGHT: { text: '같은 방향', cls: 'bg-ok text-white' },
  WRONG: { text: '반대 방향', cls: 'bg-line text-sub' },
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
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs text-sub">내가 설득력 있다고 고른 근거</p>
        {graded.length > 0 && (
          <span className="text-xs font-bold">
            인용 방향 일치 {right}/{graded.length}{horizon && <span className="font-medium text-sub"> · {horizon}거래일{horizon === 3 ? ' 중간' : ' 최종'}</span>}
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
          판정은 빗나갔지만 맞는 방향의 근거를 골랐어요. 어느 해석에 더 무게를 뒀는지 토론과 함께 돌아보세요.
        </p>
      )}
      {userHit === true && graded.length > 0 && right === 0 && (
        <p className="rounded-xl bg-ground px-3 py-2.5 text-[13px] leading-relaxed">
          판정은 맞았지만 고른 근거는 반대쪽이었어요. 고른 근거와 최종 결정이 어떻게 연결됐는지 돌아보세요.
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
