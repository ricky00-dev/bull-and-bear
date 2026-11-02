import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { ScoreChip } from '../components/ScoreBits'
import { TabBar } from '../components/TabBar'
import { Card, ErrorNotice, Screen, Skeleton } from '../components/ui'
import { api } from '../lib/api'
import { monthDay } from '../lib/format'
import type { MyStats } from '../lib/types'
import { DECISION_LABEL } from '../lib/types'

const DECISION_COLOR = { BUY: 'text-up-ink', HOLD: 'text-ink', SELL: 'text-down-ink' } as const

export function MyJudgmentsPage() {
  const list = useQuery({ queryKey: ['me', 'judgments'], queryFn: api.myJudgments })
  const stats = useQuery({ queryKey: ['me', 'stats'], queryFn: api.myStats })
  const items = list.data?.items ?? []

  return (
    <Screen>
      <header className="pt-safe px-5">
        <h1 className="pb-3 pt-5 text-2xl font-extrabold tracking-tight">내 판정</h1>
      </header>

      <main className="flex flex-1 flex-col gap-3.5 px-5 pb-6">
        {stats.data && stats.data.judged > 0 && <StatsCard s={stats.data} />}

        {list.isLoading && (
          <>
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </>
        )}
        {list.isError && <ErrorNotice message="판정 기록을 불러오지 못했어요" onRetry={() => list.refetch()} />}

        {list.isSuccess && items.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <p className="text-[17px] font-extrabold">아직 판정한 종목이 없어요</p>
            <p className="text-sm text-sub">AI 토론을 보고 첫 판정을 내려 보세요</p>
            <Link to="/" className="mt-2 flex min-h-12 items-center rounded-xl bg-ink px-5 text-[15px] font-bold text-white">
              종목 찾기
            </Link>
          </div>
        )}

        {items.length > 0 && (
          <ul className="flex flex-col gap-2.5">
            {items.map((j) => (
              <li key={j.judgmentId}>
                <Link to={`/me/judgments/${j.judgmentId}`} className="flex flex-col gap-2.5 rounded-2xl border border-line bg-white p-4">
                  <div className="flex items-baseline justify-between">
                    <span className="text-[16px] font-extrabold">{j.stockName}</span>
                    <span className="text-xs text-sub">{monthDay(j.tradeDate)} 판정</span>
                  </div>
                  <p className="text-[13px] text-sub">
                    나 <b className={DECISION_COLOR[j.decision]}>{DECISION_LABEL[j.decision]}</b>
                    <span className="mx-1.5 text-line">|</span>
                    AI <b className={DECISION_COLOR[j.moderatorDecision]}>{DECISION_LABEL[j.moderatorDecision]}</b>
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {j.scores.map((s) => (
                      <ScoreChip key={s.horizonDays} s={s} />
                    ))}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
      <TabBar />
    </Screen>
  )
}

function StatsCard({ s }: { s: MyStats }) {
  const total = s.evidenceHabit.reduce((a, h) => a + h.count, 0)
  return (
    <Card className="flex flex-col gap-4">
      <div className="grid grid-cols-3 gap-2 text-center">
        <Stat value={s.userHitRate === null ? '–' : `${s.userHitRate}%`} label="내 적중률" />
        <Stat value={s.moderatorHitRate === null ? '–' : `${s.moderatorHitRate}%`} label="AI 적중률" />
        <Stat value={`${s.beatAi}회`} label="AI를 이긴 판정" />
      </div>
      <p className="text-center text-[11px] text-sub">
        {s.scored > 0 ? `7거래일 채점 ${s.scored}건 기준` : `판정 ${s.judged}건 · 첫 7거래일 채점을 기다리는 중`}
      </p>
      {total > 0 && (
        <div className="flex flex-col gap-2 border-t border-line-soft pt-3">
          <p className="text-[13px] font-extrabold">내가 자주 고르는 근거</p>
          {s.evidenceHabit.some((h) => h.graded > 0) && (
            <p className="-mt-1 text-[11px] text-sub">맞은 방향: 그 근거를 인용한 쪽으로 주가가 움직인 횟수 (7거래일 기준)</p>
          )}
          {s.evidenceHabit.map((h) => (
            <div key={h.category} className="grid grid-cols-[64px_1fr_32px] items-center gap-2 text-xs">
              <span className="text-sub">{h.label}</span>
              <span className="h-2 rounded-full bg-line-soft">
                <span className="block h-2 rounded-full bg-ink" style={{ width: `${(h.count / total) * 100}%` }} />
              </span>
              <span className="text-right font-bold">{Math.round((h.count / total) * 100)}%</span>
              {h.graded > 0 && (
                <span className="col-start-2 col-end-4 -mt-1 text-[11px] text-sub">
                  맞은 방향 {h.right}/{h.graded}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xl font-extrabold">{value}</span>
      <span className="text-[11px] text-sub">{label}</span>
    </div>
  )
}
