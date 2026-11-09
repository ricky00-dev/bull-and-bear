import { motion } from 'motion/react'
import { useState } from 'react'
import { chipText } from '../lib/glossary'
import { MAX_EVIDENCE_PICKS } from '../lib/evidence'
import type { Evidence, Round, Side, Statement } from '../lib/types'
import { ROUND_LABEL } from '../lib/types'
import { ICONS } from './icons'
import { Mascot } from './Mascot'
import { TermText } from './TermText'
import { Icon } from './ui'

/** 퀴즈는 기존 말풍선, 토론은 같은 라운드의 양쪽을 맞춘 카드로 읽는다. */
export function StatementBubble({ s, onChip, comparison = false, selected = [], onPick, previousId }: {
  s: { side: Side; round: Round; attempts: number; statement: Statement }
  onChip: (e: Evidence) => void; comparison?: boolean; selected?: string[]
  onPick?: (sourceId: string) => void; previousId?: number
}) {
  const bull = s.side === 'bull'
  const tone = bull
    ? { name: 'text-up-ink', border: 'border-up-line', chip: 'border-up-line bg-up-soft' }
    : { name: 'text-down-ink', border: 'border-down-line', chip: 'border-down-line bg-down-soft' }
  const [open, setOpen] = useState(false)
  const claim = s.statement.claim.trim()
  const raw = s.statement.argument?.replace(/[ \t]*\[E\d+\]/g, '').trim() ?? ''
  const argument = (raw.startsWith(claim) ? raw.slice(claim.length) : raw).trim()
  return (
    <motion.article
      // 불은 왼쪽, 베어는 오른쪽에서 들어온다
      initial={{ opacity: 0, x: bull ? -28 : 28, scale: 0.97 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      transition={{ type: 'spring', stiffness: 260, damping: 24 }}
      aria-label={`${bull ? '매수' : '매도'} 측 ${ROUND_LABEL[s.round]}`} className={`flex min-w-0 flex-col gap-2 ${comparison ? 'h-full' : bull ? 'mr-9' : 'ml-9'}`}>
      <header className={`flex flex-wrap items-center justify-between gap-2 text-sm font-bold ${tone.name}`}>
        <span className="flex items-center gap-1.5"><Mascot side={s.side} facing={bull ? 1 : -1} size={28} still />{bull ? '매수 측' : '매도 측'} <span className="font-normal text-sub">{ROUND_LABEL[s.round]}</span></span>
        {previousId !== undefined && <a href={`#turn-${previousId}`} className="pressable flex min-h-touch items-center rounded-control px-2 text-xs font-medium text-sub underline underline-offset-4">앞선 상대 주장</a>}
      </header>
      <div className={`flex flex-1 flex-col gap-3 rounded-panel border bg-white p-4 ${tone.border}`}>
        <p className="text-[15px] font-medium leading-relaxed"><TermText text={claim} /></p>
        {argument && open && <p className="whitespace-pre-line border-t border-line-soft pt-3 text-sm leading-relaxed text-sub"><TermText text={argument} /></p>}
        {argument && <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="pressable -ml-2 flex min-h-touch self-start items-center gap-2 rounded-control px-2 text-[13px] font-bold text-sub">{open ? '설명 접기' : '주장 자세히 읽기'}<Icon d={open ? 'M6 15l6-6 6 6' : 'M6 9l6 6 6-6'} size={14} /></button>}
        <div className="mt-auto flex flex-col gap-2">
          {s.statement.evidence.map(e => {
            const picked = selected.includes(e.source_id)
            const full = !picked && selected.length >= MAX_EVIDENCE_PICKS
            return <div key={e.ref} className="flex items-stretch gap-2">
              <button type="button" onClick={() => onChip(e)} className={`flex min-h-touch min-w-0 flex-1 items-center justify-between gap-2 rounded-control border px-3 py-2 text-left text-[13px] font-medium ${tone.chip}`}>
                <span>{chipText(e.source_id, e.value)}</span><Icon d={ICONS.chevron} size={14} className="shrink-0" />
              </button>
              {onPick && <button type="button" aria-label={`${chipText(e.source_id, e.value)} ${picked ? '선택 해제' : '판정 근거로 담기'}`} aria-pressed={picked} disabled={full} onClick={() => onPick(e.source_id)}
                className={`flex min-h-touch min-w-touch shrink-0 items-center justify-center rounded-control border px-2 text-xs font-bold ${picked ? 'border-ink bg-ink text-white' : 'pressable border-line bg-white text-sub disabled:opacity-40'}`}>
                {picked ? <><Icon d={ICONS.check} size={16} /><span className="sr-only">담음</span></> : '담기'}
              </button>}
            </div>
          })}
          {s.statement.evidence.length === 0 && <p className="text-[13px] text-sub">연결된 근거가 없어요.</p>}
        </div>
      </div>
      <p className="text-xs leading-relaxed text-sub">{s.attempts > 1 ? `${s.attempts - 1}회 수정 후 통과 · ` : ''}{s.statement.evidence.some(e => e.value !== null) ? '인용 수치 검증을 통과한 발언' : '근거 검토를 통과한 발언'} · 해석은 직접 판단해요</p>
    </motion.article>
  )
}
