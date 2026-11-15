import type { Decision } from './types'
export const JUDGMENT_DRAFT_PREFIX = 'bb.judgment-draft.'
export interface JudgmentDraft { decision: Decision | null; confidence: number; memo: string }
export const EMPTY_JUDGMENT_DRAFT: JudgmentDraft = { decision: null, confidence: 70, memo: '' }
export function decodeJudgmentDraft(raw: string | null): JudgmentDraft {
  try {
    const data: unknown = JSON.parse(raw ?? 'null')
    if (!data || typeof data !== 'object' || Array.isArray(data)) return {...EMPTY_JUDGMENT_DRAFT}
    const d = data as Record<string, unknown>
    return {
      decision: d.decision === 'BUY' || d.decision === 'HOLD' || d.decision === 'SELL' ? d.decision : null,
      confidence: typeof d.confidence === 'number' && Number.isFinite(d.confidence) ? Math.max(50,Math.min(100,50+Math.round((d.confidence-50)/10)*10)) : 70,
      memo: typeof d.memo === 'string' ? d.memo.slice(0,200) : '',
    }
  } catch { return {...EMPTY_JUDGMENT_DRAFT} }
}
