import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Card, ErrorNotice, Screen, Skeleton, TopBar } from '../components/ui'
import { api } from '../lib/api'
import { monthDay } from '../lib/format'
import type { Rate, Report, ReportHorizon } from '../lib/types'

const pctOf = (r: Rate) => (r.n ? Math.round((r.hits / r.n) * 100) : null)

/**
 * AI 성적표: 토론 AI vs 혼자 판단한 AI vs 기준선. 숫자보다 "표본이 이만큼"이라는 한계를 같이 보여주는 게 중요하다.
 * 기본은 정식 운용만. 예비 운용은 엔진이 달라 실험 숫자와 섞지 않고, 따로 켜서 볼 수만 있다.
 */
export function ReportPage() {
  const [all, setAll] = useState(false)
  const [days, setDays] = useState(7)
  const q = useQuery({ queryKey: ['report', all], queryFn: () => api.report(all) })
  const r = q.data
  const h = r?.horizons.find((x) => x.days === days)

  return (
    <Screen>
      <TopBar title="AI 성적표" sub="토론 AI vs 혼자 판단한 AI" back="/my" />
      <main className="flex flex-1 flex-col gap-3.5 px-5 pb-6">
        <div className="flex gap-2">
          <Toggle on={!all} onClick={() => setAll(false)}>
            정식 운용
          </Toggle>
          <Toggle on={all} onClick={() => setAll(true)}>
            예비 운용 포함
          </Toggle>
        </div>

        {q.isError && <ErrorNotice message="성적표를 불러오지 못했어요" onRetry={() => q.refetch()} />}
        {!r && !q.isError && (
          <>
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-64 w-full" />
          </>
        )}
        {r && h && (
          <>
            <Period r={r} />
            <div className="grid grid-cols-2 gap-2">
              {r.horizons.map((x) => (
                <Toggle key={x.days} on={days === x.days} onClick={() => setDays(x.days)}>
                  {x.days}거래일 뒤 {x.days === 7 ? '(주 지표)' : ''}
                </Toggle>
              ))}
            </div>
            {h.debate.n === 0 ? (
              <Empty r={r} days={days} />
            ) : (
              <>
                <Scoreboard h={h} />
                <Decisions h={h} />
                {r.visitors.n > 0 && <Visitors v={r.visitors} />}
              </>
            )}
            <Limits r={r} />
          </>
        )}
      </main>
    </Screen>
  )
}

function Period({ r }: { r: Report }) {
  return (
    <Card className="flex flex-col gap-1">
      <p className="text-xs font-bold text-mod">{r.official ? '정식 운용' : '예비 운용 포함'}</p>
      <p className="text-[15px] font-extrabold">
        {r.from ? `${monthDay(r.from)} ~ ${r.to ? monthDay(r.to) : ''}` : `${monthDay(r.start)}부터`}
        {r.stocks > 0 && ` · ${r.stocks}종목`}
      </p>
      <p className="text-xs leading-relaxed text-sub">
        매일 장 마감 뒤 같은 종목을 토론하고, 실제 주가로 코스피 대비 채점해요. 보류는 ±{r.holdBand}%p 이내면 맞힌 거예요.
      </p>
    </Card>
  )
}

function Empty({ r, days }: { r: Report; days: number }) {
  return (
    <Card className="flex flex-col items-center gap-2 py-8 text-center">
      <p className="text-[17px] font-extrabold">아직 채점된 토론이 없어요</p>
      <p className="text-[13px] leading-relaxed text-sub">
        {r.official
          ? `정식 운용은 ${monthDay(r.start)}에 시작해요. 첫 ${days}거래일 결과는 그로부터 ${days}거래일 뒤에 나와요.`
          : `전향 운용 토론의 ${days}거래일 결과가 쌓이면 여기에 보여요.`}
      </p>
    </Card>
  )
}

function Scoreboard({ h }: { h: ReportHorizon }) {
  const paired = h.single.n > 0
  const rows: { label: string; rate: Rate | null; note?: string; tone: string }[] = [
    { label: '토론 AI', rate: h.debate, tone: 'bg-mod' },
    {
      label: '혼자 판단한 AI',
      rate: paired ? h.single : null,
      note: paired ? undefined : '아직 없음',
      tone: 'bg-ink',
    },
    { label: '항상 보류', rate: h.alwaysHold, tone: 'bg-faint' },
    { label: '항상 매수', rate: h.alwaysBuy, tone: 'bg-faint' },
    { label: '무작위로 찍기', rate: null, note: '약 33%', tone: 'bg-faint' },
  ]
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-extrabold">{h.days}거래일 뒤 적중률</h2>
        <span className="text-[11px] text-sub">{h.debate.n}건 채점</span>
      </div>
      <ul className="flex flex-col gap-2.5">
        {rows.map((row, i) => {
          const p = row.rate ? pctOf(row.rate) : row.label === '무작위로 찍기' ? 33 : null
          return (
            <li key={row.label} className={`flex flex-col gap-1 ${i === 2 ? 'border-t border-line-soft pt-2.5' : ''}`}>
              <div className="flex items-baseline justify-between text-[13px]">
                <span className={i < 2 ? 'font-extrabold' : 'text-sub'}>{row.label}</span>
                <span className={i < 2 ? 'text-base font-extrabold' : 'font-bold text-sub'}>
                  {row.note ?? (p === null ? '–' : `${p}%`)}
                  {row.rate && i < 2 && <span className="ml-1 text-[11px] font-bold text-sub">({row.rate.hits}/{row.rate.n})</span>}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-line-soft">
                <div className={`h-2 rounded-full ${row.tone}`} style={{ width: `${p ?? 0}%` }} />
              </div>
            </li>
          )
        })}
      </ul>
      {paired && h.debatePaired.n !== h.debate.n && (
        <p className="text-[11px] leading-relaxed text-sub">
          혼자 판단한 AI가 있는 {h.debatePaired.n}건만 놓고 보면 토론 AI는 {pctOf(h.debatePaired)}%예요.
        </p>
      )}
    </Card>
  )
}

function Decisions({ h }: { h: ReportHorizon }) {
  const bar = (d: { buy: number; hold: number; sell: number }) => {
    const t = d.buy + d.hold + d.sell || 1
    return (
      <div className="flex h-3 gap-0.5 overflow-hidden rounded-full bg-line">
        <span className="bg-up" style={{ width: `${(d.buy / t) * 100}%` }} />
        <span className="bg-faint" style={{ width: `${(d.hold / t) * 100}%` }} />
        <span className="bg-down" style={{ width: `${(d.sell / t) * 100}%` }} />
      </div>
    )
  }
  const label = (d: { buy: number; hold: number; sell: number }) => `매수 ${d.buy} · 보류 ${d.hold} · 매도 ${d.sell}`
  return (
    <Card className="flex flex-col gap-3">
      <h2 className="text-sm font-extrabold">어떤 판정을 냈나</h2>
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-xs">
          <span className="font-bold">토론 AI</span>
          <span className="text-sub">{label(h.debateDecisions)}</span>
        </div>
        {bar(h.debateDecisions)}
      </div>
      {h.single.n > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="flex justify-between text-xs">
            <span className="font-bold">혼자 판단한 AI</span>
            <span className="text-sub">{label(h.singleDecisions)}</span>
          </div>
          {bar(h.singleDecisions)}
        </div>
      )}
      <p className="text-[11px] leading-relaxed text-sub">보류만 많이 내면 적중률이 높아 보일 수 있어서, "항상 보류" 기준선과 같이 봐야 해요.</p>
    </Card>
  )
}

function Visitors({ v }: { v: { n: number; userHits: number; aiHits: number } }) {
  const p = (x: number) => Math.round((x / v.n) * 100)
  return (
    <Card className="flex flex-col gap-2">
      <h2 className="text-sm font-extrabold">사람 vs AI</h2>
      <div className="flex items-baseline gap-4">
        <span className="flex flex-col">
          <span className="text-3xl font-extrabold">{p(v.userHits)}%</span>
          <span className="text-xs text-sub">사람</span>
        </span>
        <span className="flex flex-col">
          <span className="text-3xl font-extrabold text-mod">{p(v.aiHits)}%</span>
          <span className="text-xs text-mod">AI 중재자</span>
        </span>
      </div>
      <p className="text-[11px] text-sub">같은 토론에 대한 판정 {v.n}건을 7거래일 뒤 결과로 비교했어요.</p>
    </Card>
  )
}

function Limits({ r }: { r: Report }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl bg-surface-2 px-1 text-[11px] leading-relaxed text-sub">
      <p>⚠ 표본이 적어 10%p 안팎의 차이는 우연일 수 있어요. 같은 날 종목들은 시장 흐름을 같이 타요.</p>
      <p>
        {r.official
          ? '정식 운용 토론만 셌어요. 예비 운용은 AI 엔진이 달라 섞지 않아요.'
          : '예비 운용은 AI 엔진이 달라 정식 실험 숫자와 다르게 봐야 해요.'}
      </p>
      <p>교육용 모의 실험이에요. AI 판정은 투자 권유가 아니에요.</p>
    </div>
  )
}

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={`min-h-10 rounded-xl px-3.5 text-[13px] font-bold ${on ? 'bg-point text-on-point' : 'bg-surface-2 text-sub'}`}
    >
      {children}
    </button>
  )
}
