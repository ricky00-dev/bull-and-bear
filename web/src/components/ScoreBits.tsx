import { dueLabel, pctPoint } from '../lib/format'
import type { ScoreView } from '../lib/types'

/** 목록 카드에 붙는 채점 상태 한 줄: "3일 적중 +2.31%p" / "7일 채점 11/2 예정" */
export function ScoreChip({ s, who = 'user' }: { s: ScoreView; who?: 'user' | 'moderator' }) {
  if (s.status === 'PENDING') {
    return (
      <span className="rounded-md bg-ground px-2 py-1 text-[11px] font-bold text-sub">
        {s.horizonDays}일 · {dueLabel(s.scheduledDate)}
      </span>
    )
  }
  const hit = who === 'user' ? s.userHit : s.moderatorHit
  return (
    <span className={`rounded-md px-2 py-1 text-[11px] font-bold ${hit ? 'bg-ok-soft text-ok' : 'bg-line-soft text-sub'}`}>
      {s.horizonDays}일 {hit ? '적중' : '빗나감'} {s.excessReturn !== null && pctPoint(s.excessReturn)}
    </span>
  )
}

/**
 * 초과수익이 어느 구간에 떨어졌는지 보여주는 막대.
 * 왼쪽 파랑 = 매도 적중, 가운데 회색 = 보류 적중(±band), 오른쪽 빨강 = 매수 적중.
 */
export function BandBar({ excess, band }: { excess: number; band: number }) {
  const RANGE = 8 // 막대 양 끝 = ±8%p
  const pos = (v: number) => ((Math.max(-RANGE, Math.min(RANGE, v)) + RANGE) / (2 * RANGE)) * 100
  const lo = pos(-band)
  const hi = pos(band)
  return (
    <div className="flex flex-col gap-1.5">
      <div
        className="relative h-7 rounded-lg"
        style={{
          background: `linear-gradient(90deg, var(--color-down-soft) 0 ${lo}%, #eef0f3 ${lo}% ${hi}%, var(--color-up-soft) ${hi}% 100%)`,
        }}
        role="img"
        aria-label={`초과수익 ${pctPoint(excess)}`}
      >
        <span className="absolute -bottom-1 -top-1 w-[3px] -translate-x-1/2 rounded-sm bg-ink" style={{ left: `${pos(excess)}%` }} />
      </div>
      <div className="flex justify-between text-[11px] font-bold">
        <span className="text-down-ink">매도 적중</span>
        <span className="text-sub">보류 적중 ±{band}%p</span>
        <span className="text-up-ink">매수 적중</span>
      </div>
    </div>
  )
}
