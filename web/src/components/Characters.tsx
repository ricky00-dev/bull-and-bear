import { useEffect, useState } from 'react'
import bearFace from '../assets/characters/bear-face.png'
import bearPoster from '../assets/characters/bear-poster.jpg'
import bearVideo from '../assets/characters/bear.mp4'
import bear from '../assets/characters/bear.png'
import bullFace from '../assets/characters/bull-face.png'
import bullPoster from '../assets/characters/bull-poster.jpg'
import bullVideo from '../assets/characters/bull.mp4'
import bull from '../assets/characters/bull.png'
import owlFace from '../assets/characters/owl-face.png'

/** B-7 캐릭터 (docs/DESIGN.md 5절). 황소 = 매수 AI, 곰 = 매도 AI, 부엉이 = 중재자 */
export type Speaker = 'bull' | 'bear' | 'owl'

const FACE: Record<Speaker, string> = { bull: bullFace, bear: bearFace, owl: owlFace }
const NAME: Record<Speaker, string> = { bull: '매수 AI', bear: '매도 AI', owl: 'AI 중재자' }

/** 화자 얼굴(원형 34~44). 옆에 이름이 같이 나오므로 기본은 장식 이미지 */
export function Avatar({ who, size = 40, label = false }: { who: Speaker; size?: number; label?: boolean }) {
  return (
    <img
      src={FACE[who]}
      alt={label ? NAME[who] : ''}
      width={size}
      height={size}
      loading="lazy"
      className="shrink-0 rounded-full bg-surface-2 object-cover"
      style={{ width: size, height: size }}
    />
  )
}

/** 홈 첫 화면 히어로: 황소(왼쪽)와 곰(오른쪽) 전신. 정지 이미지 (영상은 토론 무대에만) */
export function HeroPair() {
  return (
    <div className="flex items-end justify-between" role="img" aria-label="매수 AI 황소와 매도 AI 곰">
      <img src={bull} alt="" className="h-[158px] w-auto" />
      <img src={bear} alt="" className="h-[158px] w-auto" />
    </div>
  )
}

function usePrefersReducedMotion() {
  const query = '(prefers-reduced-motion: reduce)'
  const [reduced, setReduced] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches)
  useEffect(() => {
    const media = window.matchMedia(query)
    const onChange = () => setReduced(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  return reduced
}

/**
 * 토론 무대(16:9). 지금 말하는 쪽 캐릭터의 8초 무음 루프 영상 하나만 튼다 (DESIGN.md 6절).
 * 모션 줄이기 설정이면 영상 대신 포스터. 영상 바탕이 surface와 같은 색이라 경계가 보이지 않는다.
 */
export function DebateStage({ side, caption }: { side: 'bull' | 'bear'; caption: string }) {
  const reduced = usePrefersReducedMotion()
  const poster = side === 'bull' ? bullPoster : bearPoster
  const video = side === 'bull' ? bullVideo : bearVideo
  return (
    <figure className="relative overflow-hidden rounded-panel bg-surface">
      <div className="aspect-video w-full">
        {reduced ? (
          <img src={poster} alt="" className="size-full object-contain" />
        ) : (
          <video key={side} src={video} poster={poster} muted loop playsInline autoPlay aria-hidden="true" className="size-full object-contain" />
        )}
      </div>
      <figcaption className="absolute left-3 top-3 flex items-center gap-1.5 rounded-chip bg-ground/70 px-2.5 py-1 text-xs font-bold backdrop-blur">
        <span className="size-1.5 animate-pulse-dot rounded-full bg-point" aria-hidden="true" />
        {caption}
      </figcaption>
    </figure>
  )
}
