export type Decision = 'BUY' | 'HOLD' | 'SELL'
export type Side = 'bull' | 'bear'
export type Round = 'opening' | 'rebuttal' | 'closing' | 'extra'
export type DebateStatus = 'RUNNING' | 'COMPLETED' | 'FAILED'

export interface StockItem {
  ticker: string
  name: string
  market: string
  close: number
  changePct: number
  eligible: boolean
  blockReason: string | null
}

export interface StockDetail {
  ticker: string
  name: string
  market: string
  close: number
  changePct: number
  asOf: string
  eligible: boolean
  reasons: string[]
  sparkline: number[]
  todayDebate: { id: string; status: DebateStatus; createdAt: string } | null
  /** 오늘 새 토론을 더 시작할 수 있는지. 오늘 이미 있는 토론은 이와 상관없이 볼 수 있다 */
  quota: { left: number; limit: number; budgetOpen: boolean }
}

export interface Debate {
  id: string
  ticker: string
  stockName: string
  status: DebateStatus
  reused: boolean
  snapshotId: string | null
  tradeDate: string | null
  basePrice: number | null
  createdAt: string
}

/** 워커 형식 그대로 (snake_case) */
export interface Evidence {
  ref: string
  source_id: string
  value: number | null
  interpretation: string
}

export interface Statement {
  claim: string
  argument: string
  evidence: Evidence[]
}

export interface Score {
  relevance: number
  materiality: number
  rebuttal: number
  risk_awareness: number
  comment: string
}

export interface Verdict {
  decision: Decision
  confidence: number
  reasoning: string
  decisive_evidence: string[]
  scores: { bull: Score; bear: Score }
}

export interface Reveal {
  mine: { id: string; decision: Decision; confidence: number; evidencePicks: string[]; memo: string | null }
  verdict: Verdict
  agrees: boolean
  crowd: { buy: number; hold: number; sell: number; total: number }
}

export interface ScoreView {
  horizonDays: number
  status: 'PENDING' | 'SCORED'
  /** 주말만 뺀 예상일 */
  scheduledDate: string
  scoredTradeDate: string | null
  /** % 단위 */
  stockReturn: number | null
  indexReturn: number | null
  /** %p 단위 */
  excessReturn: number | null
  userHit: boolean | null
  moderatorHit: boolean | null
}

export interface JudgmentView {
  judgmentId: string
  debateId: string
  ticker: string
  stockName: string
  tradeDate: string
  basePrice: number
  decision: Decision
  confidence: number
  moderatorDecision: Decision
  createdAt: string
  scores: ScoreView[]
}

export interface JudgmentDetail {
  judgment: JudgmentView
  evidencePicks: string[]
  memo: string | null
  decisiveEvidence: string[]
  holdBand: number
}

export interface MyStats {
  judged: number
  scored: number
  userHits: number
  moderatorHits: number
  beatAi: number
  userHitRate: number | null
  moderatorHitRate: number | null
  evidenceHabit: { category: string; label: string; count: number }[]
}

export const DECISION_LABEL: Record<Decision, string> = { BUY: '매수', HOLD: '보류', SELL: '매도' }
export const ROUND_LABEL: Record<Round, string> = { opening: '주장', rebuttal: '반박', closing: '최종 변론', extra: '추가 질문' }
