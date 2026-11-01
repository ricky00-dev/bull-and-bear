import { Link } from 'react-router'
import { TERMS } from '../lib/glossary'

/** 한국 시간 날짜로 고르므로 같은 날엔 모두 같은 용어를 본다 */
function todayIndex(): number {
  const kstDay = Math.floor((Date.now() + 9 * 3600_000) / 86_400_000)
  return kstDay % TERMS.length
}

/** 홈의 오늘의 용어. 토론을 안 봐도 하루 하나씩 배울 거리 */
export function TodayTerm() {
  const t = TERMS[todayIndex()]
  return (
    <section className="flex flex-col gap-2 rounded-2xl border border-line bg-white p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-bold text-mod">오늘의 용어</h2>
        <Link to="/glossary" className="text-xs font-bold text-sub">
          용어 사전
        </Link>
      </div>
      <p className="text-[17px] font-extrabold">{t.label}</p>
      <p className="text-sm leading-relaxed text-sub">{t.desc}</p>
    </section>
  )
}
