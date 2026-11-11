import { useState } from 'react'
import { chipText } from '../lib/glossary'
import { MAX_EVIDENCE_PICKS } from '../lib/evidence'
import type { Evidence, Round, Side, Statement } from '../lib/types'
import { ROUND_LABEL } from '../lib/types'
import { ICONS } from './icons'
import { TermText } from './TermText'
import { Avatar } from './Characters'
import { Icon } from './ui'

/** 기본은 말풍선(매수 왼쪽, 매도 오른쪽 지그재그). comparison은 양쪽을 같은 높이 카드로 맞춘다. */
export function StatementBubble({ s, onChip, comparison = false, selected = [], onPick, previousId }: {
  s: { side: Side; round: Round; attempts: number; statement: Statement }
  onChip: (e: Evidence) => void; comparison?: boolean; selected?: string[]
  onPick?: (sourceId: string) => void; previousId?: number
}) {
  const bull = s.side === 'bull'
  const tone = bull
    ? { name: 'text-up-ink', border: 'border-up-line', chip: 'bg-surface-2' }
    : { name: 'text-down-ink', border: 'border-down-line', chip: 'bg-surface-2' }
  const [open, setOpen] = useState(false)
  const claim = s.statement.claim.trim()
  const raw = s.statement.argument?.replace(/[ \t]*\[E\d+\]/g, '').trim() ?? ''
  const argument = (raw.startsWith(claim) ? raw.slice(claim.length) : raw).trim()
  return (
    <article aria-label={`${bull ? '매수' : '매도'} 측 ${ROUND_LABEL[s.round]}`} className={`flex min-w-0 flex-col gap-2 ${comparison ? 'h-full' : bull ? 'mr-9 md:mr-[22%]' : 'ml-9 md:ml-[22%]'}`}>
      <header className={`flex flex-wrap items-center justify-between gap-2 text-sm font-bold ${tone.name}`}>
        <span className="flex items-center gap-2"><Avatar who={bull ? 'bull' : 'bear'} size={34} />{bull ? '매수 AI' : '매도 AI'} <span className="font-normal text-sub">{ROUND_LABEL[s.round]}</span></span>
        {previousId !== undefined && <a href={`#turn-${previousId}`} className="pressable flex min-h-touch items-center rounded-control px-2 text-xs font-medium text-sub underline underline-offset-4">앞선 상대 주장</a>}
      </header>
      <div className={`flex flex-1 flex-col gap-3 rounded-panel bg-surface p-4`}>
        <p className="text-[15px] font-medium leading-relaxed"><TermText text={claim} /></p>
        {argument && open && <p className="whitespace-pre-line border-t border-line-soft pt-3 text-sm leading-relaxed text-sub"><TermText text={argument} /></p>}
        {argument && <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="pressable -ml-2 flex min-h-touch self-start items-center gap-2 rounded-control px-2 text-[13px] font-bold text-sub">{open ? '설명 접기' : '주장 자세히 읽기'}<Icon d={open ? 'M6 15l6-6 6 6' : 'M6 9l6 6 6-6'} size={14} /></button>}
        <div className="mt-auto flex flex-col gap-2">
          {s.statement.evidence.map(e => {
            const picked = selected.includes(e.source_id)
            const full = !picked && selected.length >= MAX_EVIDENCE_PICKS
            return <div key={e.ref} className="flex items-stretch gap-2">
              <button type="button" onClick={() => onChip(e)} className={`flex min-h-touch min-w-0 flex-1 items-center justify-between gap-2 rounded-chip px-3 py-2 text-left text-[13px] font-medium ${tone.chip}`}>
                <span>{chipText(e.source_id, e.value, e.observation?.label)}</span><Icon d={ICONS.chevron} size={14} className="shrink-0" />
              </button>
              {onPick && <button type="button" aria-label={`${chipText(e.source_id, e.value, e.observation?.label)} ${picked ? '선택 해제' : '판정 근거로 담기'}`} aria-pressed={picked} disabled={full} onClick={() => onPick(e.source_id)}
                className={`flex min-h-touch min-w-touch shrink-0 items-center justify-center rounded-control border px-2 text-xs font-bold ${picked ? 'border-point bg-point text-on-point' : 'pressable border-line bg-surface text-sub disabled:opacity-40'}`}>
                {picked ? <><Icon d={ICONS.check} size={16} /><span className="sr-only">담음</span></> : '담기'}
              </button>}
            </div>
          })}
          {s.statement.evidence.length === 0 && <p className="text-[13px] text-sub">연결된 근거가 없어요.</p>}
        </div>
      </div>
      <p className="text-xs leading-relaxed text-sub">{s.attempts > 1 ? `${s.attempts - 1}회 다시 작성 · ` : ''}AI의 발언이에요 · 근거와 해석은 직접 판단해요</p>
    </article>
  )
}
