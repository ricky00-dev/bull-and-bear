import type { Round, Side, Statement } from './types'

export interface AcceptedStatement {
  seq: number
  side: Side
  round: Round
  attempts: number
  statement: Statement
}

export interface StreamState {
  connection: 'connecting' | 'open' | 'reconnecting' | 'failed'
  phase: 'connecting' | 'running' | 'moderating' | 'sealed' | 'failed'
  statements: AcceptedStatement[]
  /** 지금 무슨 일이 일어나는지 한 줄 (예: "매도 측 AI가 재무제표를 확인하는 중") */
  activity: string
  currentRound: Round | null
  /** 응답 형식 처리에 실패한 마지막 이유 */
  lastRejection: string | null
  extraQuestion: string | null
  /** 스냅샷 기준일 (snapshot_created) */
  asOf: string | null
  error: string | null
  lastSeq: number
}

type Action = { seq: number; type: string; data: Record<string, unknown> } | { type: 'open' } | { type: 'lost' } | { type: 'reset' } | { type: 'connect_failed' }

const SIDE_LABEL: Record<Side, string> = { bull: '매수 측', bear: '매도 측' }
const TOOL_ACTIVITY: Record<string, string> = {
  get_price_metrics: '시세 지표를 살펴보는 중',
  get_financials: '재무제표를 확인하는 중',
  get_valuation: '밸류에이션을 계산해 보는 중',
  get_disclosures: '공시를 확인하는 중',
  get_news: '뉴스를 읽는 중',
}

export const initialStreamState: StreamState = {
  connection: 'connecting',
  phase: 'connecting',
  statements: [],
  activity: '토론을 준비하는 중',
  currentRound: null,
  lastRejection: null,
  extraQuestion: null,
  asOf: null,
  error: null,
  lastSeq: 0,
}

export function reduceDebateStream(state: StreamState, action: Action): StreamState {
  if (action.type === 'reset') return {...initialStreamState}
  if (action.type === 'open') return { ...state, connection: 'open', phase: state.phase === 'connecting' ? 'running' : state.phase, activity: state.connection === 'reconnecting' ? '연결했어요. 진행 상황을 확인하는 중' : state.activity }
  if (action.type === 'lost') return { ...state, connection: 'reconnecting', activity: '연결이 끊겨 다시 잇는 중' }
  if (action.type === 'connect_failed') return { ...state, connection: 'failed', activity: '토론 서버에 연결하지 못했어요' }
  if (!('seq' in action) || action.seq <= state.lastSeq) return state // 재연결 시 중복 무시

  const s = { ...state, lastSeq: action.seq }
  const d = action.data
  const side = d.side as Side | undefined
  switch (action.type) {
    case 'snapshot_created':
      return { ...s, asOf: (d.as_of as string) ?? null, activity: '데이터를 고정했어요. 토론을 시작해요' }
    case 'turn_started':
      return { ...s, currentRound: d.round as Round, activity: `${SIDE_LABEL[side!]} AI가 생각하는 중` }
    case 'tool_call':
      return { ...s, activity: `${SIDE_LABEL[side!]} AI가 ${TOOL_ACTIVITY[d.tool as string] ?? '데이터를 보는 중'}` }
    case 'statement_rejected': {
      const issues = (d.issues as { message: string }[] | undefined) ?? []
      return {
        ...s,
        lastRejection: issues[0]?.message ?? null,
        activity: `${SIDE_LABEL[side!]}의 응답 형식을 다시 작성하고 있어요`,
      }
    }
    case 'statement_accepted':
      return {
        ...s,
        statements: [
          ...s.statements,
          { seq: action.seq, side: side!, round: d.round as Round, attempts: d.attempts as number, statement: d.statement as Statement },
        ],
      }
    case 'extra_round_requested':
      return { ...s, extraQuestion: d.question as string, activity: '중재자가 추가 질문을 했어요' }
    case 'moderator_started':
      return { ...s, phase: 'moderating', activity: '중재자가 판정하는 중' }
    case 'debate_sealed':
      return { ...s, phase: 'sealed', activity: '토론이 끝났어요 · 중재자 판정은 봉인됐어요' }
    case 'debate_failed':
      return {
        ...s,
        phase: 'failed',
        error: ((d.error as { message?: string } | undefined)?.message) ?? '토론을 이어갈 수 없어요',
      }
    default:
      return s
  }
}
