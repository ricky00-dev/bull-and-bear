import { AnimatePresence, motion } from 'motion/react'
import { useMemo } from 'react'
import { countBySide, sideMood } from '../lib/debateStage'
import type { StreamState } from '../lib/useDebateStream'
import type { Side } from '../lib/types'
import { ROUND_LABEL } from '../lib/types'
import { ICONS } from './icons'
import { Mascot, type MascotMood } from './Mascot'
import { Icon } from './ui'

/**
 * 토론 맨 위 무대. 불(매수)과 베어(매도)가 마주 보고, 지금 라운드에서 아직 발언 전인 쪽은 생각하는 몸짓,
 * 새 발언이 도착하면 그쪽이 상대에게 한 번 들이받는다. 판정 봉인 뒤에는 둘 다 쉬고 가운데에 자물쇠.
 */
export function DebateStage({ stream }: { stream: Pick<StreamState, 'phase' | 'currentRound' | 'statements'> }) {
  const { phase, currentRound, statements } = stream
  const done = phase === 'sealed'
  const moderating = phase === 'moderating'
  const count = useMemo(() => countBySide(statements), [statements])

  const mood = (side: Side) => sideMood(stream, side)
  const status = (side: Side) => {
    if (phase === 'failed') return '토론 중단'
    if (done) return `발언 ${count[side]}번`
    if (moderating) return '중재자 판정 대기'
    return mood(side) === 'thinking' ? '생각하는 중' : count[side] ? '상대 발언 기다리는 중' : '준비하는 중'
  }
  const center = done ? '판정 봉인' : moderating ? '중재자 판정 중' : currentRound ? ROUND_LABEL[currentRound] : '준비'

  return (
    <section aria-label="토론 무대" className="relative flex items-center justify-between gap-2 overflow-hidden rounded-panel border border-line bg-white px-3 py-3">
      <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-0 w-1/2 bg-gradient-to-r from-up-soft to-transparent" />
      <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 right-0 w-1/2 bg-gradient-to-l from-down-soft to-transparent" />
      <Fighter side="bull" mood={mood('bull')} strike={count.bull} status={status('bull')} />
      <div className="relative flex min-w-0 flex-col items-center gap-1 text-center" aria-live="polite">
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={center}
            initial={{ opacity: 0, scale: 0.6, rotate: -8 }}
            animate={{ opacity: 1, scale: 1, rotate: 0 }}
            exit={{ opacity: 0, scale: 0.6 }}
            transition={{ type: 'spring', stiffness: 420, damping: 20 }}
            className={`flex items-center gap-1 whitespace-nowrap rounded-full px-3 py-1 text-xs font-extrabold ${done ? 'bg-mod text-white' : 'bg-ink text-white'}`}
          >
            {done && <Icon d={ICONS.lock} size={12} stroke={2.4} />}
            {center}
          </motion.span>
        </AnimatePresence>
        <span className="text-lg font-black italic tracking-tight text-faint">VS</span>
      </div>
      <Fighter side="bear" mood={mood('bear')} strike={count.bear} status={status('bear')} />
    </section>
  )
}

function Fighter({ side, mood, strike, status }: { side: Side; mood: MascotMood; strike: number; status: string }) {
  const bull = side === 'bull'
  return (
    <div className="relative flex w-24 shrink-0 flex-col items-center gap-1">
      <Mascot side={side} mood={mood} facing={bull ? 1 : -1} strike={strike} size={68} />
      <span className={`text-sm font-extrabold ${bull ? 'text-up-ink' : 'text-down-ink'}`}>{bull ? '매수 AI 불' : '매도 AI 베어'}</span>
      <span className="flex items-center gap-1 text-[11px] text-sub">
        {mood === 'thinking' && <ThinkingDots />}
        {status}
      </span>
    </div>
  )
}

function ThinkingDots() {
  return (
    <span aria-hidden="true" className="flex gap-0.5">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="size-1 rounded-full bg-faint"
          animate={{ y: [0, -3, 0] }}
          transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.12 }}
        />
      ))}
    </span>
  )
}
