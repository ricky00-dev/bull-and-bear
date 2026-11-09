import { animate, type JSAnimation } from 'animejs'
import { useEffect, useRef } from 'react'
import type { Side } from '../lib/types'

/**
 * 매수 AI(불, 빨강)와 매도 AI(베어, 파랑) 얼굴. viewBox 96×96.
 * 앱 아이콘(public/icon.svg)과 로고가 같은 그림을 쓴다. 고치면 아이콘도 같이 고친다.
 */
const ART: Record<Side, { body: string; dark: string; light: string }> = {
  bull: { body: '#d92d20', dark: '#a8231a', light: '#f8c9c1' },
  bear: { body: '#2b6fe0', dark: '#1d4fb0', light: '#cfdffb' },
}

/** 얼굴 모양만. facing: 눈동자가 보는 방향 (-1 왼쪽, 1 오른쪽) */
export function MascotArt({ side, facing = 0 }: { side: Side; facing?: number }) {
  const c = ART[side]
  const look = facing * 2.2
  return (
    <g className="m-body">
      {side === 'bull' ? (
        <>
          <path className="m-ear" d="M22 44c-9-1-15-6-16-11 7-2 14 0 19 5z" fill={c.dark} />
          <path className="m-ear" d="M74 44c9-1 15-6 16-11-7-2-14 0-19 5z" fill={c.dark} />
          <path d="M28 30C17 27 12 17 15 6c4 9 10 14 20 15z" fill="#fbe6c4" />
          <path d="M68 30c11-3 16-13 13-24-4 9-10 14-20 15z" fill="#fbe6c4" />
        </>
      ) : (
        <>
          <circle className="m-ear" cx="25" cy="27" r="12" fill={c.body} />
          <circle className="m-ear" cx="71" cy="27" r="12" fill={c.body} />
          <circle cx="25" cy="27" r="6.5" fill={c.light} />
          <circle cx="71" cy="27" r="6.5" fill={c.light} />
        </>
      )}
      <ellipse cx="48" cy="53" rx="30" ry="28" fill={c.body} />
      {/* 눈썹: 마주 보고 따지는 표정 */}
      <path d="M31 39l11 4M65 39l-11 4" stroke="#111318" strokeWidth="3.4" strokeLinecap="round" />
      <g className="m-eyes">
        <ellipse cx="38" cy="50" rx="5.4" ry="6" fill="#fff" />
        <ellipse cx="58" cy="50" rx="5.4" ry="6" fill="#fff" />
        <circle cx={38 + look} cy="51" r="3.2" fill="#111318" />
        <circle cx={58 + look} cy="51" r="3.2" fill="#111318" />
      </g>
      <ellipse cx="48" cy="67" rx={side === 'bull' ? 19 : 15} ry={side === 'bull' ? 12 : 11} fill={c.light} />
      {side === 'bull' ? (
        <>
          <ellipse cx="41" cy="64" rx="2.6" ry="3.2" fill={c.dark} />
          <ellipse cx="55" cy="64" rx="2.6" ry="3.2" fill={c.dark} />
        </>
      ) : (
        <ellipse cx="48" cy="61.5" rx="5.4" ry="3.6" fill="#111318" />
      )}
      <path className="m-mouth" d="M42 71q6 5 12 0" stroke="#111318" strokeWidth="2.8" strokeLinecap="round" fill="none" />
    </g>
  )
}

/** 로고: 불과 베어가 머리를 맞댄 모습 (앱 아이콘과 같은 구도) */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg viewBox="0 0 154 96" height={size} width={(size * 154) / 96} aria-hidden="true" className="shrink-0">
      <MascotArt side="bull" facing={1} />
      <g transform="translate(58 0)">
        <MascotArt side="bear" facing={-1} />
      </g>
    </svg>
  )
}

export type MascotMood = 'idle' | 'thinking' | 'done'

/**
 * 움직이는 캐릭터. strike가 바뀔 때마다 상대 쪽으로 한 번 들이받는다(새 발언 도착).
 * 움직임 줄이기 설정이면 가만히 있는다.
 */
export function Mascot({ side, mood = 'idle', facing = 0, strike = 0, size = 72, still = false, className = '' }: {
  side: Side; mood?: MascotMood; facing?: number; strike?: number; size?: number; still?: boolean; className?: string
}) {
  const ref = useRef<SVGSVGElement>(null)
  const moving = !still && !prefersReducedMotion()

  useEffect(() => {
    const svg = ref.current
    if (!svg || !moving) return
    const body = svg.querySelector('.m-body')
    const anims: JSAnimation[] = [
      animate(svg.querySelectorAll('.m-eyes'), { scaleY: [1, 0.1, 1], duration: 220, loop: true, loopDelay: side === 'bull' ? 2600 : 3400, ease: 'inOutQuad' }),
    ]
    if (mood === 'thinking') {
      anims.push(animate(body!, { rotate: [-4, 4], translateY: [0, -2], duration: 700, loop: true, alternate: true, ease: 'inOutSine' }))
      anims.push(animate(svg.querySelectorAll('.m-mouth'), { scaleX: [1, 0.6], duration: 350, loop: true, alternate: true, ease: 'inOutSine' }))
    } else {
      anims.push(animate(body!, { translateY: [0, mood === 'done' ? -1 : -2.5], duration: 1600, loop: true, alternate: true, ease: 'inOutSine' }))
    }
    if (side === 'bull') {
      anims.push(animate(svg.querySelectorAll('.m-ear'), { rotate: [0, -8, 0], duration: 500, loop: true, loopDelay: 2200, ease: 'inOutSine' }))
    }
    return () => anims.forEach((a) => a.revert())
  }, [mood, side, moving])

  useEffect(() => {
    const svg = ref.current
    if (!svg || !moving || strike === 0) return
    // 몸통 안쪽 그룹과 겹치지 않게 svg 자체를 움직인다
    const toward = facing || (side === 'bull' ? 1 : -1)
    const a = animate(svg, {
      translateX: [0, toward * 14, 0],
      rotate: [0, toward * 8, 0],
      scale: [1, 1.08, 1],
      duration: 520,
      ease: 'outBack',
    })
    return () => {
      a.revert()
    }
  }, [strike, facing, side, moving])

  return (
    <svg ref={ref} viewBox="0 0 96 96" width={size} height={size} aria-hidden="true" className={`mascot shrink-0 overflow-visible ${className}`}>
      <MascotArt side={side} facing={facing} />
    </svg>
  )
}

function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
