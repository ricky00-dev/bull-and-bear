export const FACT_METRICS = {
  close: { label: '종가', unit: 'KRW/share' },
  per_ttm: { label: 'PER (최근 12개월)', unit: 'x' },
  pbr: { label: 'PBR', unit: 'x' },
  roe_ttm: { label: 'ROE (최근 12개월)', unit: '%' },
  operating_margin_ttm: { label: '영업이익률 (최근 12개월)', unit: '%' },
  market_cap: { label: '시가총액', unit: 'KRW' },
} as const
export type FactMetric = keyof typeof FACT_METRICS
export interface FactQuery { metric: FactMetric; asOf?: string; unit: string }
interface RagBase {
  snapshot_id: string; context_id: string; ticker: string; snapshot_as_of: string
  answerability: string; reasons: string[]
}
export interface DocumentResult extends RagBase {
  mode: 'documents'; answer_scope: string
  documents: { chunk_id: string; text: string; horizons: string[]; applicability: string; limitations: string[] }[]
}
export interface FactResult extends RagBase {
  mode: 'facts'
  facts: { fact_id: string; ticker: string; value: number; unit: string; as_of: string; source: string; inputs: string[]; verified_lineage: string[] }[]
}
const REASONS: Record<string, string> = {
  required_fact_missing: '저장된 자료에 해당 지표가 없습니다.',
  fact_value_unavailable: '값이 없거나 사용할 수 없는 수치입니다.',
  fact_date_mismatch: '요청한 날짜와 저장된 수치의 기준일이 다릅니다.',
  unit_mismatch: '요청 단위가 지표의 단위와 다릅니다.',
  ticker_mismatch: '자료의 종목이 요청 종목과 다릅니다.',
  unconfirmed_or_future_date: '확정되지 않은 날짜의 수치는 조회할 수 없습니다.',
}
export function factReason(code: string) { return REASONS[code] ?? '저장된 수치의 근거 검증을 통과하지 못했습니다.' }
