import { MAX_EVIDENCE_PICKS, type EvidenceCitation } from '../lib/evidence'
import { describe, formatValue } from '../lib/glossary'
import type { Evidence } from '../lib/types'
import { ROUND_LABEL } from '../lib/types'
import { BottomSheet } from './ui'

const KIND: Record<string, string> = { PX: '시세 지표', VAL: '주가·재무 지표', FIN: '재무제표', DISC: '공시', NEWS: '뉴스' }

/** 발언의 인용값·해석과 저장 수치의 출처를 구분한다. 없는 원문 링크는 만들지 않는다. */
export function EvidenceSheet({ evidence, sourceId, citations = [], asOf, onClose, selected = [], onPick }: {
  evidence?: Evidence; sourceId?: string; citations?: EvidenceCitation[]; asOf?: string | null
  onClose: () => void; selected?: string[]; onPick?: (sourceId: string) => void
}) {
  const id = evidence?.source_id ?? sourceId ?? ''
  const info = describe(id)
  const picked = selected.includes(id)
  const full = !picked && selected.length >= MAX_EVIDENCE_PICKS
  const uses = citations.length ? citations : evidence ? [{ evidence, side: null, round: null }] : []
  return (
    <BottomSheet label={`${info.label} 근거 확인`} onClose={onClose}>
      <div className="flex flex-col gap-1">
        <p className="text-[13px] text-sub">근거 확인</p>
        <h2 className="text-xl font-bold">{info.label}</h2>
        {evidence?.value != null && <p className="text-2xl font-bold">{formatValue(id, evidence.value)}</p>}
      </div>
      {info.desc && <p className="text-sm leading-relaxed text-sub">{info.desc}</p>}
      <dl className="flex flex-col gap-3 rounded-panel bg-surface-2 p-4 text-[13px]">
        <div className="flex flex-wrap justify-between gap-2"><dt className="text-sub">출처 구분</dt><dd>{KIND[id.split('.')[0]] ?? '토론 근거'}</dd></div>
        <div className="flex flex-wrap justify-between gap-2"><dt className="text-sub">토론 기준일</dt><dd>{asOf ?? '기준일 확인 중'}</dd></div>
        <div className="flex flex-wrap justify-between gap-2"><dt className="text-sub">근거 ID</dt><dd className="break-all">{id}</dd></div>
      </dl>
      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-bold">발언에서 어떻게 해석했나요?</h3>
        {uses.map((use, index) => <div key={`${use.side}-${use.round}-${index}`} className="flex flex-col gap-2 rounded-panel bg-surface-2 p-4">
          <p className={`text-[13px] font-bold ${use.side === 'bull' ? 'text-up-ink' : use.side === 'bear' ? 'text-down-ink' : 'text-ink'}`}>{use.side ? `${use.side === 'bull' ? '매수 측' : '매도 측'} · ${ROUND_LABEL[use.round!]}` : '이 발언의 해석'}</p>
          {use.evidence.value !== null && <p className="text-[13px] text-sub">인용값 {formatValue(id, use.evidence.value)}</p>}
          <p className="text-sm leading-relaxed">{use.evidence.interpretation || '해석이 제공되지 않았어요.'}</p>
        </div>)}
        {uses.length === 0 && <p className="text-sm text-sub">이 근거의 발언 내용을 아직 불러오지 못했어요.</p>}
        <p className="text-[13px] leading-relaxed text-sub">수치 검증을 통과해도 전망과 해석이 맞다는 뜻은 아니에요. 같은 수치를 양쪽이 다르게 해석할 수 있어요.</p>
      </section>
      {onPick && <div className="flex flex-col gap-2"><button type="button" aria-pressed={picked} disabled={full} onClick={() => onPick(id)} className={`min-h-touch rounded-control border px-4 text-sm font-bold ${picked ? 'border-point bg-point text-on-point' : 'pressable border-line disabled:text-faint'}`}>{picked ? '판정 근거에서 빼기' : '내 판정 근거로 담기'}</button><p className="text-xs text-sub">{full ? '최대 2개예요. 담아둔 근거를 해제하면 바꿀 수 있어요.' : '담은 근거는 다음 판정 화면으로 이어져요.'}</p></div>}
    </BottomSheet>
  )
}
