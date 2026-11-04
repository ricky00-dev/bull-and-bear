import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { MAX_EVIDENCE_PICKS, type EvidenceCitation } from '../lib/evidence'
import { describe, formatValue } from '../lib/glossary'
import { FACT_METRICS, factReason, type FactMetric } from '../lib/rag'
import type { Evidence } from '../lib/types'
import { ROUND_LABEL } from '../lib/types'
import { BottomSheet } from './ui'

const METRIC: Record<string, FactMetric> = { 'PX.CLOSE': 'close', 'VAL.PER_TTM': 'per_ttm', 'VAL.PBR': 'pbr', 'VAL.ROE_TTM': 'roe_ttm', 'VAL.OP_MARGIN_TTM': 'operating_margin_ttm', 'VAL.MKTCAP': 'market_cap' }
const KIND: Record<string, string> = { PX: '시세 지표', VAL: '주가·재무 지표', FIN: '재무제표', DISC: '공시', NEWS: '뉴스' }

/** 발언의 인용값·해석과 저장 수치의 출처를 구분한다. 없는 원문 링크는 만들지 않는다. */
export function EvidenceSheet({ evidence, sourceId, citations = [], asOf, debateId, onClose, selected = [], onPick }: {
  evidence?: Evidence; sourceId?: string; citations?: EvidenceCitation[]; asOf?: string | null; debateId?: string
  onClose: () => void; selected?: string[]; onPick?: (sourceId: string) => void
}) {
  const id = evidence?.source_id ?? sourceId ?? ''
  const info = describe(id)
  const metric = METRIC[id]
  const stored = useQuery({
    queryKey: ['evidence-fact', debateId, id],
    queryFn: () => api.ragFacts(debateId!, { metric, unit: FACT_METRICS[metric].unit }),
    enabled: false, retry: false,
  })
  const fact = stored.data?.answerability === 'supported_fact' ? stored.data.facts.find(f => f.fact_id === id) : undefined
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
      <dl className="flex flex-col gap-3 rounded-panel border border-line p-4 text-[13px]">
        <div className="flex flex-wrap justify-between gap-2"><dt className="text-sub">출처 구분</dt><dd>{KIND[id.split('.')[0]] ?? '토론 근거'}</dd></div>
        <div className="flex flex-wrap justify-between gap-2"><dt className="text-sub">토론 기준일</dt><dd>{asOf ?? '기준일 확인 중'}</dd></div>
        <div className="flex flex-wrap justify-between gap-2"><dt className="text-sub">근거 ID</dt><dd className="break-all">{id}</dd></div>
      </dl>
      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-bold">발언에서 어떻게 해석했나요?</h3>
        {uses.map((use, index) => <div key={`${use.side}-${use.round}-${index}`} className="flex flex-col gap-2 rounded-panel bg-ground p-4">
          <p className={`text-[13px] font-bold ${use.side === 'bull' ? 'text-up-ink' : use.side === 'bear' ? 'text-down-ink' : 'text-ink'}`}>{use.side ? `${use.side === 'bull' ? '매수 측' : '매도 측'} · ${ROUND_LABEL[use.round!]}` : '이 발언의 해석'}</p>
          {use.evidence.value !== null && <p className="text-[13px] text-sub">인용값 {formatValue(id, use.evidence.value)}</p>}
          <p className="text-sm leading-relaxed">{use.evidence.interpretation || '해석이 제공되지 않았어요.'}</p>
        </div>)}
        {uses.length === 0 && <p className="text-sm text-sub">이 근거의 발언 내용을 아직 불러오지 못했어요.</p>}
        <p className="text-[13px] leading-relaxed text-sub">수치 검증을 통과해도 전망과 해석이 맞다는 뜻은 아니에요. 같은 수치를 양쪽이 다르게 해석할 수 있어요.</p>
      </section>
      <section className="flex flex-col gap-3 border-t border-line pt-4">
        <h3 className="text-sm font-bold">저장 자료와 대조</h3>
        {debateId && metric ? <>
          <button type="button" disabled={stored.isFetching} onClick={() => stored.refetch()} className="pressable min-h-touch rounded-control border border-line px-3 text-sm font-bold disabled:opacity-50">{stored.isFetching ? '저장 수치 확인 중…' : stored.isError ? '저장 수치 다시 확인' : '저장 수치 확인하기'}</button>
          {stored.isError && <p role="alert" className="text-[13px] leading-relaxed text-sub">저장 수치를 조회하지 못했어요. 위 인용값을 원본 조회 결과로 보지 마세요.</p>}
          {stored.isSuccess && (fact ? <dl className="flex flex-col gap-2 text-[13px]">
            <div className="flex justify-between gap-3"><dt className="text-sub">저장 수치</dt><dd className="font-bold">{formatValue(id, fact.value)}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-sub">수치 기준일</dt><dd>{fact.as_of}</dd></div>
            <div className="flex flex-wrap justify-between gap-3"><dt className="text-sub">자료 출처</dt><dd className="break-all">{fact.source}</dd></div>
          </dl> : <p className="text-[13px] leading-relaxed text-sub">{stored.data.reasons.length ? stored.data.reasons.map(factReason).join(' ') : '이 근거에 대응하는 저장 수치를 확인할 수 없어요.'}</p>)}
        </> : <p className="text-[13px] leading-relaxed text-sub">이 근거의 원본 수치·원문 연결 정보는 현재 제공되지 않아요. 위 값은 토론에서 인용한 값이에요.</p>}
      </section>
      {onPick && <div className="flex flex-col gap-2"><button type="button" aria-pressed={picked} disabled={full} onClick={() => onPick(id)} className={`min-h-touch rounded-control border px-4 text-sm font-bold ${picked ? 'border-ink bg-ink text-white' : 'pressable border-line disabled:text-faint'}`}>{picked ? '판정 근거에서 빼기' : '내 판정 근거로 담기'}</button><p className="text-xs text-sub">{full ? '최대 2개예요. 담아둔 근거를 해제하면 바꿀 수 있어요.' : '담은 근거는 다음 판정 화면으로 이어져요.'}</p></div>}
    </BottomSheet>
  )
}
