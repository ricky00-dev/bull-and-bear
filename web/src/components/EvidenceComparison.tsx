import { useState } from 'react'
import { evidenceCitations, type DebateTurn } from '../lib/evidence'
import { describe } from '../lib/glossary'
import { EvidenceSheet } from './EvidenceSheet'
import { Card, Icon } from './ui'
import { ICONS } from './icons'

export function EvidenceComparison({ mine, decisive, turns, asOf, debateId, memo }: {
  mine: string[]; decisive: string[]; turns: DebateTurn[]; asOf?: string | null; debateId: string; memo?: string | null
}) {
  const [sourceId, setSourceId] = useState<string | null>(null)
  const shared = [...new Set(mine)].filter(id => decisive.includes(id))
  const citations = sourceId ? evidenceCitations(turns, sourceId) : []
  return <>
    <Card className="flex flex-col gap-4">
      <div className="flex flex-col gap-1"><h2 className="text-base font-bold">어떤 근거를 중요하게 봤나요?</h2><p className="text-[13px] leading-relaxed text-sub">{shared.length ? `함께 고른 근거 ${shared.length}개. 같은 근거를 골라도 해석은 다를 수 있어요.` : '나와 AI가 중요하게 본 근거를 비교해 보세요.'}</p></div>
      <div className="grid gap-4 md:grid-cols-2">
        {[{title:'내가 고른 근거', ids:[...new Set(mine)], empty:'선택한 근거가 없어요.'}, {title:'AI의 결정적 근거', ids:[...new Set(decisive)], empty:'결정적 근거가 제공되지 않았어요.'}].map(group => <section key={group.title} className="flex min-w-0 flex-col gap-2">
          <h3 className="text-sm font-bold">{group.title}</h3>
          {group.ids.length === 0 && <p className="rounded-control bg-surface-2 p-3 text-[13px] text-sub">{group.empty}</p>}
          <ul className="flex flex-col gap-2">{group.ids.map(id => <li key={id}>
            <button type="button" onClick={() => setSourceId(id)} className="pressable flex min-h-touch w-full items-center justify-between gap-3 rounded-control bg-surface-2 px-3 py-3 text-left text-sm">
              <span className="flex min-w-0 flex-col gap-1"><span className="font-medium">{describe(id).label}</span>{shared.includes(id) && <span className="text-xs text-sub">나와 AI가 함께 선택</span>}</span><Icon d={ICONS.chevron} size={16} className="shrink-0 text-sub" />
            </button>
          </li>)}</ul>
        </section>)}
      </div>
      {memo && <div className="rounded-panel bg-surface-2 p-4"><h3 className="mb-2 text-[13px] font-bold">그때 남긴 내 메모</h3><p className="whitespace-pre-wrap text-sm leading-relaxed">{memo}</p></div>}
    </Card>
    {sourceId && <EvidenceSheet sourceId={sourceId} evidence={citations[0]?.evidence} citations={citations} debateId={debateId} asOf={asOf} onClose={() => setSourceId(null)} />}
  </>
}
