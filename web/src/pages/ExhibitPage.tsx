import { useQuery } from '@tanstack/react-query'
import { QRCodeSVG } from 'qrcode.react'
import { useEffect } from 'react'
import bearFace from '../assets/characters/bear-face.png'
import bear from '../assets/characters/bear.png'
import bullFace from '../assets/characters/bull-face.png'
import bull from '../assets/characters/bull.png'
import owlFace from '../assets/characters/owl-face.png'
import { Logo } from '../components/ui'
import { api } from '../lib/api'
import type { RankEntry } from '../lib/types'

/** 관람객이 폰으로 찍을 주소. 노트북이 배포 주소가 아닌 곳(예: 로컬)에서 띄울 때만 VITE_PUBLIC_URL로 바꾼다 */
const ENTRY_URL: string = import.meta.env.VITE_PUBLIC_URL || window.location.origin

/**
 * 전시장 노트북 화면(/exhibit). 큰 QR + 오늘 퀴즈 랭킹 + 오늘의 토론 참여 현황.
 * 아무도 만지지 않는 화면이라 알아서 새로 고치고, 메뉴·안내 창 없이 한 화면으로 끝난다.
 */
export function ExhibitPage() {
  useWakeLock()
  const ranking = useQuery({ queryKey: ['ranking', false], queryFn: () => api.quizRanking(false), refetchInterval: 15_000 })
  const feed = useQuery({ queryKey: ['feed'], queryFn: api.feed, refetchInterval: 30_000 })
  const debates = feed.data?.items ?? []
  const judged = debates.reduce((n, d) => n + d.judged, 0)

  return (
    <div className="relative flex min-h-dvh w-full flex-col gap-[2.5vw] overflow-hidden bg-ground p-[2.5vw] lg:h-dvh lg:flex-row">
      <ExhibitChart />

      <section className="relative flex min-h-0 flex-col justify-between gap-[1.2vw] lg:w-[40%]">
        <div className="flex flex-col gap-[1.2vw]">
          <div className="origin-left scale-150">
            <Logo />
          </div>
          <p className="pt-[1.2vw] text-[clamp(14px,1.1vw,22px)] font-bold text-point">AI 토론으로 연습하는 투자 판단</p>
          <h1 className="text-[clamp(30px,3.8vw,72px)] font-black leading-[1.12] tracking-tight">
            같은 자료, <span className="text-up-ink">다른</span> <span className="text-down-ink">결론</span>.
            <br />
            판단은 <span className="text-point">내가</span>.
          </h1>
          <p className="text-[clamp(15px,1.25vw,24px)] leading-relaxed text-sub">
            <b className="text-up-ink">매수</b> AI와 <b className="text-down-ink">매도</b> AI의 근거를 읽고 내가 먼저 판정해요.
            <br />
            실제 주가로 나와 AI를 함께 채점해요.
          </p>
        </div>

        <div className="flex items-center gap-[2vw] rounded-panel bg-surface/85 p-[1.6vw] backdrop-blur">
          {/* QR은 카메라가 읽도록 흰 바탕 + 여백(quiet zone)을 둔다 */}
          <div className="ex-glow shrink-0 rounded-control bg-white p-[0.9vw]">
            <QRCodeSVG value={ENTRY_URL} size={512} marginSize={0} level="M" className="block h-auto w-[min(13vw,26vh)]" />
          </div>
          <div className="flex flex-col gap-[0.8vw]">
            <p className="text-[clamp(18px,1.8vw,34px)] font-extrabold leading-snug">
              폰 카메라로
              <br />
              찍으면 바로 시작
            </p>
            <p className="text-[clamp(13px,1vw,18px)] text-sub">설치·가입 없이 1분이면 돼요</p>
            <p className="break-all text-[clamp(12px,0.9vw,16px)] font-bold text-faint">{ENTRY_URL.replace(/^https?:\/\//, '')}</p>
          </div>
        </div>

        <div className="flex items-end justify-between">
          <img src={bull} alt="매수 AI 황소" className="ex-float h-[min(17vh,13vw)] w-auto drop-shadow-[0_12px_30px_rgb(229_56_59/0.35)]" />
          <p className="pb-[0.6vw] text-center text-[clamp(11px,0.8vw,14px)] text-sub">교육용 모의 서비스예요.<br />AI 판정은 투자 권유가 아니에요.</p>
          <img src={bear} alt="매도 AI 곰" className="ex-float ex-float-late h-[min(17vh,13vw)] w-auto drop-shadow-[0_12px_30px_rgb(47_111_235/0.35)]" />
        </div>
      </section>

      <section className="relative flex min-h-0 min-w-0 flex-1 flex-col gap-[1.6vw]">
        <div className="flex min-h-0 flex-1 flex-col gap-[0.8vw] overflow-hidden rounded-panel bg-surface/85 p-[1.8vw] backdrop-blur">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[clamp(18px,1.7vw,32px)] font-extrabold">오늘의 퀴즈 랭킹</h2>
            {ranking.data && <span className="text-[clamp(13px,1.1vw,20px)] text-sub">{ranking.data.players}명 도전</span>}
          </div>
          {ranking.data && ranking.data.top.length === 0 && <EmptyRanking />}
          <ol className="flex flex-col gap-[0.3vw]">
            {ranking.data?.top.slice(0, 8).map((e, i) => (
              <RankRow key={i} e={e} />
            ))}
          </ol>
        </div>

        <div className="flex shrink-0 flex-col gap-[0.8vw] rounded-panel bg-surface/85 p-[1.8vw] backdrop-blur">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[clamp(18px,1.7vw,32px)] font-extrabold">오늘의 토론</h2>
            {debates.length > 0 && <span className="text-[clamp(13px,1.1vw,20px)] text-sub">판정 {judged}건</span>}
          </div>
          {debates.length === 0 && <p className="text-[clamp(14px,1.2vw,22px)] text-sub">오늘 토론을 준비하고 있어요</p>}
          <ul className="grid grid-cols-2 gap-[0.8vw] xl:grid-cols-3">
            {debates.slice(0, 6).map((d) => (
              <li key={d.debateId} className="flex items-center justify-between gap-2 rounded-control bg-surface-2 px-[1.2vw] py-[0.7vw]">
                <span className="flex min-w-0 items-center gap-[0.6vw]">
                  <span className={`size-[0.6vw] min-h-2 min-w-2 shrink-0 rounded-full ${d.status === 'COMPLETED' ? 'bg-ok' : 'animate-pulse-dot bg-point'}`} />
                  <span className="truncate text-[clamp(14px,1.2vw,22px)] font-bold">{d.stockName}</span>
                </span>
                <span className="shrink-0 text-[clamp(12px,1vw,18px)] text-sub">{d.judged}명 판정</span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  )
}

/** 아무도 퀴즈를 안 풀었을 때. 빈 상자 대신 첫 도전을 부른다 */
function EmptyRanking() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-[1.2vw] text-center">
      <div className="flex -space-x-[1vw]">
        {[bullFace, owlFace, bearFace].map((src) => (
          <img key={src} src={src} alt="" className="size-[min(6vw,11vh)] rounded-full ring-4 ring-surface" />
        ))}
      </div>
      <p className="text-[clamp(20px,2vw,38px)] font-black">오늘 첫 1위의 주인공이 되어 보세요</p>
      <p className="text-[clamp(14px,1.2vw,22px)] text-sub">QR을 찍고 타임머신 퀴즈 5문제를 풀면 여기에 이름이 올라가요</p>
    </div>
  )
}

const MEDAL = ['bg-[rgb(255_196_61/0.16)] text-[#ffd36b]', 'bg-white/8 text-[#dfe3ea]', 'bg-[rgb(205_127_50/0.16)] text-[#e3a46a]']

function RankRow({ e }: { e: RankEntry }) {
  const top = e.rank <= 3
  return (
    <li className={`animate-rise flex items-center gap-[1.2vw] rounded-control px-[1vw] py-[0.45vw] ${top ? MEDAL[e.rank - 1] : ''}`}>
      <span className="w-[3vw] min-w-8 text-center text-[clamp(16px,1.5vw,28px)] font-black">{top ? ['🥇', '🥈', '🥉'][e.rank - 1] : e.rank}</span>
      <span className="min-w-0 flex-1 truncate text-[clamp(16px,1.4vw,26px)] font-bold text-ink">{e.name}</span>
      <span className="text-[clamp(12px,1vw,18px)] text-sub">{e.answered}문제 중</span>
      <span className="w-[5vw] min-w-12 text-right text-[clamp(18px,1.6vw,30px)] font-black">{e.hits}</span>
    </li>
  )
}

/** 랜딩과 같은 배경: 같은 점에서 출발해 빨강(상승)은 위로, 파랑(하락)은 아래로 갈라지는 선과 바닥의 캔들 */
function ExhibitChart() {
  const start = { x: 0, y: 320 }
  const up = walk(start, { x: 1200, y: 60 }, 7)
  const down = walk(start, { x: 1200, y: 560 }, 19)
  return (
    <svg aria-hidden viewBox="0 0 1200 675" preserveAspectRatio="xMidYMid slice" className="pointer-events-none absolute inset-0 h-full w-full opacity-60">
      <g opacity="0.22">
        {Array.from({ length: 40 }, (_, i) => {
          const h = 30 + rand(i * 13 + 5) * 110
          return (
            <rect key={i} className="ex-candle" style={{ animationDelay: `${i * 110}ms` }} x={8 + i * 30} y={675 - h} width="14" height={h} rx="3"
              fill={rand(i * 7 + 1) > 0.45 ? '#e5383b' : '#2f6feb'} />
          )
        })}
      </g>
      <path className="ex-draw" pathLength={1} d={toPath(up)} fill="none" stroke="#e5383b" strokeWidth="3" strokeLinejoin="round" />
      <path className="ex-draw ex-draw-late" pathLength={1} d={toPath(down)} fill="none" stroke="#2f6feb" strokeWidth="3" strokeLinejoin="round" />
    </svg>
  )
}

/** 결정적 의사 난수. 새로 고쳐도 같은 그래프가 나오게 한다 */
function rand(seed: number) {
  const x = Math.sin(seed * 9301 + 49297) * 233280
  return x - Math.floor(x)
}

function walk(from: { x: number; y: number }, to: { x: number; y: number }, seed: number) {
  const n = 26
  return Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n
    const wobble = i === 0 || i === n ? 0 : (rand(seed + i) - 0.5) * 80 * Math.sin(Math.PI * t)
    return { x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t + wobble }
  })
}

function toPath(points: { x: number; y: number }[]) {
  return points.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
}

/** 전시 내내 노트북 화면이 꺼지지 않게 (지원하는 브라우저에서만). 탭을 다시 보면 다시 잡는다 */
function useWakeLock() {
  useEffect(() => {
    let lock: WakeLockSentinel | null = null
    const request = () => {
      if (document.visibilityState !== 'visible' || !('wakeLock' in navigator)) return
      navigator.wakeLock
        .request('screen')
        .then((l) => (lock = l))
        .catch(() => {
          // 절전 막기는 덤이다. 실패하면 노트북 절전 설정으로 대신한다
        })
    }
    request()
    document.addEventListener('visibilitychange', request)
    return () => {
      document.removeEventListener('visibilitychange', request)
      lock?.release().catch(() => {})
    }
  }, [])
}
