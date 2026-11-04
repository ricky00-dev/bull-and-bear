import type { Evidence, Round, Side, Statement } from './types'

export const MAX_EVIDENCE_PICKS = 2
export const EVIDENCE_DRAFT_PREFIX = 'bb.evidence-picks.'
export interface DebateTurn { seq: number; side: Side; round: Round; attempts: number; statement: Statement }
export interface EvidenceCitation { side: Side; round: Round; evidence: Evidence }
const ROUND_ORDER: Round[] = ['opening', 'rebuttal', 'closing', 'extra']

/** 같은 라운드의 양쪽을 묶는다. 여러 추가 발언도 빠뜨리지 않는다. */
export function pairStatements(turns: DebateTurn[]) {
  return ROUND_ORDER.flatMap(round => {
    const ordered = turns.filter(s => s.round === round).toSorted((a, b) => a.seq - b.seq)
    const bull = ordered.filter(s => s.side === 'bull')
    const bear = ordered.filter(s => s.side === 'bear')
    return Array.from({ length: Math.max(bull.length, bear.length) }, (_, index) => ({
      key: `${round}-${index}`, round, index, bull: bull[index], bear: bear[index],
    }))
  })
}

/** 구조상 앞선 상대 발언으로 연결한다. 의미상 반박 대상을 추측하지 않는다. */
export function previousOpponent(turn: DebateTurn, turns: DebateTurn[]) {
  return turns.filter(s => s.side !== turn.side && s.seq < turn.seq && s.round !== turn.round)
    .toSorted((a, b) => b.seq - a.seq)[0]
}

export function evidenceCitations(turns: DebateTurn[], sourceId: string): EvidenceCitation[] {
  return turns.flatMap(s => s.statement.evidence.filter(e => e.source_id === sourceId).map(e => ({ side: s.side, round: s.round, evidence: e })))
}

export function decodeEvidencePicks(raw: string | null): string[] {
  try {
    const parsed: unknown = JSON.parse(raw ?? '[]')
    if (!Array.isArray(parsed)) return []
    return [...new Set(parsed.filter((id): id is string => typeof id === 'string' && id.length > 0 && id.length <= 160))].slice(0, MAX_EVIDENCE_PICKS)
  } catch { return [] }
}

export function toggleEvidencePick(picks: string[], id: string): string[] {
  if (picks.includes(id)) return picks.filter(p => p !== id)
  return picks.length < MAX_EVIDENCE_PICKS ? [...picks, id] : picks
}
