import { chipText } from '../lib/glossary'
import type { Evidence, Round, Side, Statement } from '../lib/types'
import { ROUND_LABEL } from '../lib/types'
import { ICONS } from './icons'
import { TermText } from './TermText'
import { Icon } from './ui'

/** 매수·매도 발언 말풍선. 토론 화면과 타임머신 퀴즈가 같이 쓴다. */
export function StatementBubble({
  s,
  onChip,
}: {
  s: { side: Side; round: Round; attempts: number; statement: Statement }
  onChip: (e: Evidence) => void
}) {
  const bull = s.side === 'bull'
  const tone = bull
    ? { badge: 'bg-up', name: 'text-up-ink', border: 'border-up-line', chip: 'border-up-line bg-up-soft', check: 'text-up-ink' }
    : { badge: 'bg-down', name: 'text-down-ink', border: 'border-down-line', chip: 'border-down-line bg-down-soft', check: 'text-down-ink' }
  const retried = s.attempts > 1

  return (
    <article className={`animate-rise flex flex-col gap-1.5 ${bull ? 'mr-9' : 'ml-9 items-end'}`}>
      <header className={`flex items-center gap-1.5 text-xs font-extrabold ${tone.name}`}>
        <span className={`rounded-md px-1.5 py-0.5 text-[11px] text-white ${tone.badge}`}>{bull ? '매수' : '매도'}</span>
        {ROUND_LABEL[s.round]}
      </header>
      <div className={`flex w-full flex-col gap-2.5 border bg-white p-3.5 ${tone.border} ${bull ? 'rounded-[4px_16px_16px_16px]' : 'rounded-[16px_4px_16px_16px]'}`}>
        <p className="text-[15px] leading-relaxed">
          <TermText text={s.statement.claim} />
        </p>
        <div className="flex flex-wrap gap-1.5">
          {s.statement.evidence.map((e) => (
            <button
              key={e.ref}
              type="button"
              onClick={() => onChip(e)}
              className={`flex min-h-8 items-center gap-1 rounded-lg border px-2.5 text-xs font-bold ${tone.chip}`}
            >
              {chipText(e.source_id, e.value)}
              <Icon d={ICONS.check} size={12} stroke={2.5} className={tone.check} />
            </button>
          ))}
        </div>
      </div>
      <p className={`px-1 text-[11px] ${retried ? 'text-warn' : 'text-sub'}`}>
        {retried
          ? `검증기가 ${s.attempts - 1}회 반려한 뒤 고친 발언 · 근거 ${s.statement.evidence.length}개 원본과 일치`
          : `근거 ${s.statement.evidence.length}개 · 원본과 일치`}
      </p>
    </article>
  )
}
