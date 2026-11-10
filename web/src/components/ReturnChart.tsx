import { monthDay } from '../lib/format'
import type { Chart } from '../lib/types'

/**
 * 판정일 전후 주가. 종목과 코스피를 판정일 종가 대비 수익률로 겹쳐 그린다.
 * 판정일 뒤 회색 띠는 "코스피 ±보류 범위"라서, 종목 선이 띠 위면 매수, 아래면 매도, 안이면 보류가 맞은 것.
 * 퀴즈 문제처럼 날짜를 가린 차트(baseDate null)는 마지막 점을 판정일로 보고 날짜 대신 "n일 뒤"로 적는다.
 */
export function ReturnChart({ chart }: { chart: Chart }) {
  const pts = chart.points
  if (pts.length < 2) {
    return <p className="py-8 text-center text-sm text-sub">차트 데이터가 아직 없어요</p>
  }
  const W = 320
  const H = 168
  const PAD = { top: 18, bottom: 22, right: 8 }
  const hidden = chart.baseDate === null
  const baseIdx = hidden ? pts.length - 1 : Math.max(0, pts.findIndex((p) => p.date === chart.baseDate))
  const band = chart.holdBand

  const values = pts.flatMap((p, i) => (i >= baseIdx ? [p.stockPct, p.indexPct + band, p.indexPct - band] : [p.stockPct, p.indexPct]))
  const lo = Math.min(...values, 0)
  const hi = Math.max(...values, 0)
  const span = hi - lo || 1
  // 판정 뒤 공간은 마지막 채점일(+2거래일)까지 미리 잡아 둔다. 판정 직후에도 "앞으로 채워질 자리"가 보이게.
  const lastHorizon = Math.max(...chart.marks.map((m) => m.horizonDays))
  const slots = Math.max(pts.length - 1, baseIdx + lastHorizon + 2)
  const x = (i: number) => (i * (W - PAD.right)) / slots
  const y = (v: number) => PAD.top + (1 - (v - lo) / span) * (H - PAD.top - PAD.bottom)
  const line = (f: (p: (typeof pts)[number]) => number, from = 0) =>
    pts
      .slice(from)
      .map((p, i) => `${x(i + from).toFixed(1)},${y(f(p)).toFixed(1)}`)
      .join(' ')

  const after = pts.slice(baseIdx)
  const bandPath =
    after.length > 1
      ? `M${after.map((p, i) => `${x(i + baseIdx).toFixed(1)},${y(p.indexPct + band).toFixed(1)}`).join(' L')} L${after
          .map((p, i) => `${x(i + baseIdx).toFixed(1)},${y(p.indexPct - band).toFixed(1)}`)
          .reverse()
          .join(' L')} Z`
      : null

  const marks = chart.marks.map((m) => ({ ...m, idx: m.reached ? pts.findIndex((p) => p.date === m.date) : -1 }))
  const pending = marks.filter((m) => m.idx < 0)

  return (
    <figure className="flex flex-col gap-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`판정일 대비 ${chart.ticker ?? '이 종목'} 수익률과 코스피 수익률`}>
        {bandPath && <path d={bandPath} fill="#eef0f3" />}
        <line x1={0} x2={W - PAD.right} y1={y(0)} y2={y(0)} stroke="var(--color-line)" strokeDasharray="3 3" />
        <line x1={x(baseIdx)} x2={x(baseIdx)} y1={PAD.top - 6} y2={H - PAD.bottom} stroke="var(--color-faint)" strokeDasharray="3 3" />
        <text x={x(baseIdx)} y={H - 6} textAnchor="middle" className="fill-sub text-[10px] font-bold">
          {hidden ? '판정일' : `판정 ${monthDay(chart.baseDate!)}`}
        </text>
        <polyline points={line((p) => p.indexPct)} fill="none" stroke="var(--color-faint)" strokeWidth={1.5} strokeLinejoin="round" />
        <polyline points={line((p) => p.stockPct)} fill="none" stroke="var(--color-ink)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {pending.map((m) => (
          <g key={m.horizonDays}>
            <line x1={x(baseIdx + m.horizonDays)} x2={x(baseIdx + m.horizonDays)} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--color-line)" />
            <text x={x(baseIdx + m.horizonDays)} y={PAD.top - 4} textAnchor="middle" className="fill-faint text-[10px] font-bold">
              {m.date ? `${m.horizonDays}일 ${monthDay(m.date)}` : `${m.horizonDays}일 뒤`}
            </text>
          </g>
        ))}
        {marks
          .filter((m) => m.idx >= 0)
          .map((m) => (
            <g key={m.horizonDays}>
              <circle cx={x(m.idx)} cy={y(pts[m.idx].stockPct)} r={4} fill="var(--color-ink)" stroke="white" strokeWidth={1.5} />
              <text x={x(m.idx)} y={y(pts[m.idx].stockPct) - 8} textAnchor="middle" className="fill-ink text-[10px] font-extrabold">
                {m.horizonDays}일
              </text>
            </g>
          ))}
      </svg>
      <figcaption className="flex flex-col gap-1 text-[11px] text-sub">
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Legend swatch="h-0.5 w-4 bg-ink" label="이 종목" />
          <Legend swatch="h-0.5 w-4 bg-faint" label="코스피" />
          {!hidden && <Legend swatch="h-2.5 w-4 rounded-sm bg-surface-2" label={`보류 구간 (코스피 ±${band}%p)`} />}
        </span>
        {hidden ? (
          <span>판정일 종가를 0%로 놓고 그 전 한 달을 그렸어요. 오른쪽 빈칸이 맞혀야 할 7거래일이에요.</span>
        ) : (
          <span>판정일 종가를 0%로 놓고 그렸어요. 판정 뒤 검은 선이 회색 띠보다 위면 매수, 아래면 매도가 맞아요.</span>
        )}
        {!hidden && pending.length > 0 && <span>{pending.map((m) => `${m.horizonDays}거래일 채점 ${monthDay(m.date!)} 예정`).join(' · ')} (휴장일이 있으면 늦어져요)</span>}
      </figcaption>
    </figure>
  )
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block ${swatch}`} />
      {label}
    </span>
  )
}
