import { describe, formatValue } from '../lib/glossary'
import type { Evidence } from '../lib/types'
import { BottomSheet } from './ui'

/** 근거 칩을 누르면 아래에서 올라오는 설명 시트. 지표를 배우는 곳. */
export function EvidenceSheet({ evidence, asOf, onClose }: { evidence: Evidence; asOf?: string | null; onClose: () => void }) {
  const info = describe(evidence.source_id)

  return (
    <BottomSheet label={`${info.label} 설명`} onClose={onClose}>
      <div className="flex flex-col gap-1">
        <p className="text-[13px] text-sub">{info.label}</p>
        {evidence.value !== null && (
          <p className="text-3xl font-extrabold tracking-tight">{formatValue(evidence.source_id, evidence.value)}</p>
        )}
      </div>
      {info.desc && <p className="text-[15px] leading-relaxed">{info.desc}</p>}
      <p className="rounded-xl bg-ground px-3.5 py-3 text-sm leading-relaxed">
        <span className="font-bold">이 토론에서는 </span>
        {evidence.interpretation}
      </p>
      <dl className="flex flex-col gap-2 rounded-xl border border-line px-3.5 py-3 text-xs text-sub">
        <div className="flex justify-between">
          <dt>근거 ID</dt>
          <dd className="font-bold text-ink">{evidence.source_id}</dd>
        </div>
        {asOf && (
          <div className="flex justify-between">
            <dt>기준일</dt>
            <dd className="font-bold text-ink">{asOf}</dd>
          </div>
        )}
        <div className="flex justify-between">
          <dt>검증</dt>
          <dd className="font-bold text-ok">원본 값과 일치</dd>
        </div>
      </dl>
    </BottomSheet>
  )
}
