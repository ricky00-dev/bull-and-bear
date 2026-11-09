import { useState } from 'react'
import { won } from '../lib/format'
import { AreaSparkline } from './charts/sparkline'

/** 최근 종가 추이 (bklit 스파크라인). 그려지며 들어오고, 손가락·마우스를 올리면 그날 종가를 보여 준다. */
export function Sparkline({ closes }: { closes: number[] }) {
  const [hover, setHover] = useState<number | null>(null)
  if (closes.length < 2) {
    return <p className="py-8 text-center text-sm text-sub">차트 데이터가 아직 없어요</p>
  }
  const lo = Math.min(...closes)
  const hi = Math.max(...closes)
  const rising = closes[closes.length - 1] >= closes[0]
  const data = closes.map((close) => ({ close }))
  const ago = hover === null ? 0 : closes.length - 1 - hover

  return (
    <figure className="flex flex-col gap-1.5">
      <p className="h-4 text-[11px] font-bold text-sub" aria-live="polite">
        {hover !== null && `${ago === 0 ? '최근 종가' : `${ago}거래일 전`} ${won(closes[hover])}`}
      </p>
      <AreaSparkline
        data={data}
        dataKey="close"
        height={120}
        color={rising ? 'var(--color-up)' : 'var(--color-down)'}
        fillOpacity={0.14}
        strokeWidth={2}
        curve="monotone"
        endDot
        dot
        crosshair="dashed"
        animate
        onHoverChange={(i) => setHover(i)}
        aria-label={`최근 ${closes.length}거래일 종가 추이`}
      />
      <figcaption className="flex flex-wrap justify-between gap-x-3 text-[11px] text-sub">
        <span>최근 {closes.length}거래일 종가 (약 {Math.round(closes.length / 20)}개월)</span>
        <span>
          최고 {won(hi)} · 최저 {won(lo)}
        </span>
      </figcaption>
    </figure>
  )
}
