import { won } from '../lib/format'

/** 최근 종가 추이. 마지막 점을 찍어 "지금"을 보여준다. */
export function Sparkline({ closes }: { closes: number[] }) {
  if (closes.length < 2) {
    return <p className="py-8 text-center text-sm text-sub">차트 데이터가 아직 없어요</p>
  }
  const W = 320
  const H = 120
  const lo = Math.min(...closes)
  const hi = Math.max(...closes)
  const span = hi - lo || 1
  const pts = closes.map((c, i) => [(i * W) / (closes.length - 1), H - 8 - ((c - lo) / span) * (H - 20)] as const)
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const [lastX, lastY] = pts[pts.length - 1]
  const rising = closes[closes.length - 1] >= closes[0]
  const color = rising ? 'var(--color-up)' : 'var(--color-down)'

  return (
    <figure className="flex flex-col gap-1.5">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`최근 ${closes.length}거래일 종가 추이`}>
        <path d={`M0,${H} L${line.replaceAll(' ', ' L')} L${W},${H} Z`} fill={color} fillOpacity={0.08} />
        <polyline points={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={lastX} cy={lastY} r={4} fill={color} />
      </svg>
      <figcaption className="flex justify-between text-[11px] text-sub">
        <span>최근 {closes.length}거래일 종가 (약 {Math.round(closes.length / 20)}개월)</span>
        <span>
          최고 {won(hi)} · 최저 {won(lo)}
        </span>
      </figcaption>
    </figure>
  )
}
