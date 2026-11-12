import { API_BASE, ApiError } from './api'

/** 관리자 화면 API. 사용자 토큰과 따로, 서버 .env의 ADMIN_TOKEN을 X-Admin-Token으로 보낸다 */

const KEY = 'bb.admin'

export function readAdminToken(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function writeAdminToken(token: string | null) {
  try {
    if (token) localStorage.setItem(KEY, token)
    else localStorage.removeItem(KEY)
  } catch {
    // 저장 못 하면 매번 입력
  }
}

async function get<T>(path: string, token: string): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/admin${path}`, { headers: { 'X-Admin-Token': token } })
  } catch {
    throw new ApiError(0, 'NETWORK', '서버에 연결할 수 없어요')
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { error?: { code: string; message: string } } | null
    throw new ApiError(res.status, body?.error?.code ?? 'UNKNOWN', body?.error?.message ?? '불러오지 못했어요')
  }
  return (await res.json()) as T
}

export type Origin = 'USER' | 'SCHEDULED' | 'BACKTEST'
export type Status = 'RUNNING' | 'COMPLETED' | 'FAILED'

export interface Cap { spentUsd: number; limitUsd: number; enabled?: boolean }

export interface Period {
  label: string
  debates: number
  completed: number
  failed: number
  running: number
  costUsd: number
  unknownCost: number
  avgCostUsd: number | null
  avgSeconds: number | null
  inputTokens: number
  outputTokens: number
  judgments: number
}

export interface Day {
  day: string
  debates: number
  failed: number
  userUsd: number
  scheduledUsd: number
  backtestUsd: number
  judgments: number
}

export interface ModelUsage {
  model: string
  debates: number
  inputTokens: number
  outputTokens: number
  cacheReadTokens: number
  cacheWriteTokens: number
}

export interface Overview {
  today: string
  health: { db: string; worker: string; status: string; forwardRun?: { status: string } }
  workerMode: string
  budget: { estimateUsd: number; perUserDailyDebates: number; user: Cap; scheduled: Cap; backtest: Cap }
  periods: Period[]
  daily: Day[]
  models: ModelUsage[]
  failures: { code: string; message: string | null; count: number; lastAt: string }[]
  stocks: { ticker: string; name: string; debates: number; costUsd: number; judgments: number; lastAt: string }[]
  users: {
    total: number
    members: number
    guests: number
    withNickname: number
    newToday: number
    activeToday: number
    top: { userId: string; nickname: string | null; guest: boolean; judgments: number; scored: number; hits: number; lastAt: string }[]
  }
  scoring: { days: number; scored: number; pending: number; userHits: number; moderatorHits: number }[]
}

export interface DebateRow {
  id: string
  ticker: string
  name: string
  origin: Origin
  status: Status
  createdAt: string
  completedAt: string | null
  seconds: number | null
  dataDate: string | null
  costUsd: number | null
  inputTokens: number | null
  outputTokens: number | null
  verdict: string | null
  confidence: number | null
  judgments: number
  requesterNickname: string | null
  requesterGuest: boolean | null
  requesterId: string | null
  error: string | null
}

export interface DebateDetail extends DebateRow {
  events: { seq: number; type: string; at: string; side: string | null; round: string | null; attempt: string | null; tool: string | null }[]
  usage: string | null
  judgmentList: { decision: string; confidence: number; at: string; nickname: string | null }[]
}

export const adminApi = {
  overview: (token: string, days: number) => get<Overview>(`/overview?days=${days}`, token),
  debates: (token: string, status: string, origin: string) =>
    get<DebateRow[]>(`/debates?limit=100&status=${status}&origin=${origin}`, token),
  debate: (token: string, id: string) => get<DebateDetail>(`/debates/${id}`, token),
}
