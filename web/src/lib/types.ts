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
  /** 같은 데이터(최신 종가)로 이미 진행된 토론. 장 마감 뒤 만든 토론은 다음 날 장 마감 전까지 재사용된다 */
  existingDebate: { id: string; status: DebateStatus; createdAt: string; dataDate: string } | null
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

/** 마이 탭 퀴즈 누적 기록. rounds는 다 푼 판 수 */
export interface QuizStats {
  rounds: number
  answered: number
  userHits: number
  aiHits: number
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

/** 홈 "오늘의 토론". 중재자 판정은 들어 있지 않다 (봉인) */
export interface FeedItem {
  debateId: string
  ticker: string
  stockName: string
  status: DebateStatus
  /** 매일 장 마감 뒤 자동으로 토론하는 종목 */
  scheduled: boolean
  dataDate: string
  createdAt: string
  judged: number
  mine: boolean
}

/** 판정일 전후 차트. 수익률은 판정일 종가 대비 % */
export interface ChartPoint {
  /** 퀴즈 문제에서는 가린다 (null) */
  date: string | null
  close: number | null
  stockPct: number
  indexPct: number
}

export interface Chart {
  /** 퀴즈 문제에서는 ticker·baseDate·marks.date를 가린다 (null) */
  ticker: string | null
  baseDate: string | null
  holdBand: number
  points: ChartPoint[]
  /** reached=false면 date는 주말만 뺀 예상일 */
  marks: { horizonDays: number; date: string | null; reached: boolean }[]
}

/** 타임머신 퀴즈 */
export interface QuizStatement {
  side: Side
  round: Round
  attempts: number
  statement: Statement
}

export interface QuizQuestion {
  idx: number
  /** "반도체 업종 대형주" */
  sector: string
  /** "2026년 11월 첫째 주" */
  period: string
  statements: QuizStatement[]
  chart: Chart
}

export interface QuizRound {
  id: string
  total: number
  userScore: number
  aiScore: number
  questions: { idx: number; decision: Decision | null; userHit: boolean | null; moderatorHit: boolean | null }[]
  /** 다 풀었으면 null */
  current: QuizQuestion | null
}

export interface QuizAnswer {
  idx: number
  stockName: string
  ticker: string
  baseDate: string
  decision: Decision
  correct: Decision
  userHit: boolean
  moderatorDecision: Decision
  moderatorReasoning: string
  /** 중재자 글의 [E1]은 [0] */
  decisiveEvidence: string[]
  moderatorHit: boolean
  stockReturn: number
  indexReturn: number
  excessReturn: number
  holdBand: number
  chart: Chart
  last: boolean
}
