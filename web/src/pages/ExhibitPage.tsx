import { useQuery } from '@tanstack/react-query'
import { QRCodeSVG } from 'qrcode.react'
import { useEffect } from 'react'
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
    <div className="flex min-h-dvh w-full flex-col gap-[2.5vw] bg-ground p-[3vw] lg:flex-row">
      <section className="flex flex-col justify-between gap-[2vw] lg:w-[40%]">
        <div className="flex flex-col gap-[1.5vw]">
          <div className="origin-left scale-150">
            <Logo />
          </div>
          <h1 className="pt-[1vw] text-[clamp(28px,3.4vw,64px)] font-extrabold leading-tight tracking-tight">
            AI 토론을 보고
            <br />
            먼저 판정해 보세요
          </h1>
          <p className="text-[clamp(15px,1.3vw,24px)] leading-relaxed text-sub">
            <b className="text-up-ink">매수</b> AI와 <b className="text-down-ink">매도</b> AI의 근거를 읽고 내가 먼저 판정해요.
            <br />
            실제 주가로 나와 AI를 함께 채점해요.
          </p>
        </div>
        <div className="flex items-center gap-[2vw] rounded-panel bg-surface p-[2vw]">
          {/* QR은 카메라가 읽도록 흰 바탕 + 여백(quiet zone)을 둔다 */}
          <div className="shrink-0 rounded-control bg-white p-[1vw]">
            <QRCodeSVG value={ENTRY_URL} size={512} marginSize={0} level="M" className="block h-auto w-[min(16vw,32vh)]" />
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
        <p className="text-[clamp(11px,0.8vw,14px)] text-sub">교육용 모의 서비스예요. AI 판정은 투자 권유가 아니에요.</p>
      </section>

      <section className="flex min-w-0 flex-1 flex-col gap-[2vw]">
        <div className="flex flex-1 flex-col gap-[1vw] rounded-panel bg-surface p-[2vw]">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[clamp(18px,1.7vw,32px)] font-extrabold">오늘의 퀴즈 랭킹</h2>
            {ranking.data && <span className="text-[clamp(13px,1.1vw,20px)] text-sub">{ranking.data.players}명 도전</span>}
          </div>
          {ranking.data && ranking.data.top.length === 0 && (
            <p className="flex flex-1 items-center justify-center text-[clamp(16px,1.5vw,28px)] font-bold text-sub">오늘 첫 번째 도전자가 되어 보세요</p>
          )}
          <ol className="flex flex-col">
            {ranking.data?.top.slice(0, 8).map((e, i) => (
              <RankRow key={i} e={e} />
            ))}
          </ol>
        </div>

        <div className="flex flex-col gap-[1vw] rounded-panel bg-surface p-[2vw]">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[clamp(18px,1.7vw,32px)] font-extrabold">오늘의 토론</h2>
            {debates.length > 0 && <span className="text-[clamp(13px,1.1vw,20px)] text-sub">판정 {judged}건</span>}
          </div>
          {debates.length === 0 && <p className="text-[clamp(14px,1.2vw,22px)] text-sub">오늘 토론을 준비하고 있어요</p>}
          <ul className="grid grid-cols-2 gap-[0.8vw] xl:grid-cols-3">
            {debates.slice(0, 6).map((d) => (
              <li key={d.debateId} className="flex items-baseline justify-between gap-2 rounded-control bg-surface-2 px-[1.2vw] py-[0.9vw]">
                <span className="truncate text-[clamp(14px,1.2vw,22px)] font-bold">{d.stockName}</span>
                <span className="shrink-0 text-[clamp(12px,1vw,18px)] text-sub">{d.judged}명</span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  )
}

function RankRow({ e }: { e: RankEntry }) {
  const medal = e.rank <= 3 ? ['🥇', '🥈', '🥉'][e.rank - 1] : null
  return (
    <li className="flex items-center gap-[1.2vw] border-b border-line-soft py-[0.7vw] last:border-b-0">
      <span className="w-[3vw] min-w-8 text-center text-[clamp(16px,1.5vw,28px)] font-extrabold">{medal ?? e.rank}</span>
      <span className="min-w-0 flex-1 truncate text-[clamp(16px,1.4vw,26px)] font-bold">{e.name}</span>
      <span className="text-[clamp(12px,1vw,18px)] text-sub">{e.answered}문제 중</span>
      <span className="w-[5vw] min-w-12 text-right text-[clamp(18px,1.6vw,30px)] font-extrabold">{e.hits}</span>
    </li>
  )
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
