import type { Chart, Debate, Decision, FeedItem, JudgmentDetail, JudgmentView, MyStats, QuizAnswer, QuizRound, QuizStats, Ranking, Report, Reveal, StockDetail, StockItem } from './types'
import type { DocumentResult, FactQuery, FactResult } from './rag'
import { EVIDENCE_DRAFT_PREFIX } from './evidence'
import { JUDGMENT_DRAFT_PREFIX } from './judgmentDraft'

type Me = { userId: string; guest: boolean; nickname: string | null }

/** 웹은 개발 서버, Capacitor 앱은 실제 서버 주소. 쿠키를 쓰지 않으므로 출처가 달라도 된다. */
export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8080'

const TOKEN_KEY = 'bb.token'
let memoryToken: string | null = null
let pendingGuest: Promise<string> | null = null

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? memoryToken
  } catch {
    return memoryToken // 사생활 보호 모드 등
  }
}

function writeToken(token: string | null) {
  memoryToken = token
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // 저장 못 해도 이번 세션은 메모리 토큰으로 동작
  }
}

/** 카카오 로그인으로 받은 이 기기용 토큰으로 바꾼다 */
export function setToken(token: string) {
  writeToken(token)
}

/** 토큰이 없으면 게스트 계정을 만든다. 가입 없이 바로 판정할 수 있게. */
export async function ensureToken(): Promise<string> {
  const existing = readToken()
  if (existing) return existing
  pendingGuest ??= fetch(`${API_BASE}/api/auth/guest`, { method: 'POST' })
    .then(async (res) => {
      if (!res.ok) throw await toError(res)
      const body = (await res.json()) as { token: string }
      writeToken(body.token)
      return body.token
    })
    .finally(() => {
      pendingGuest = null
    })
  return pendingGuest
}

async function toError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { error?: { code: string; message: string } }
    if (body.error) return new ApiError(res.status, body.error.code, body.error.message)
  } catch {
    // JSON이 아닌 오류 응답
  }
  return new ApiError(res.status, 'UNKNOWN', '잠시 후 다시 시도해 주세요')
}

async function request<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
  const token = await ensureToken()
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...init.headers },
    })
  } catch {
    throw new ApiError(0, 'NETWORK', '서버에 연결할 수 없어요')
  }
  if (res.status === 401 && !retried) {
    writeToken(null) // 토큰이 사라졌으면 게스트를 새로 만든다
    return request<T>(path, init, true)
  }
  if (!res.ok) throw await toError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** 내 기록을 지운 뒤: 토큰과 최근 검색어를 버려 다음 요청에서 새 게스트로 시작한다 */
export function resetSession() {
  writeToken(null)
  try {
    for (const key of Object.keys(sessionStorage)) if (key.startsWith(EVIDENCE_DRAFT_PREFIX) || key.startsWith(JUDGMENT_DRAFT_PREFIX)) sessionStorage.removeItem(key)
  } catch { /* 저장소를 사용할 수 없으면 메모리 세션만 초기화 */ }
  try {
    localStorage.removeItem('bb.recent')
  } catch {
    // 저장소를 못 쓰면 지울 것도 없다
  }
}

export const api = {
  ragSearch: (id: string, question: string) => request<DocumentResult>(`/api/debates/${id}/rag/search`,
    { method: 'POST', body: JSON.stringify({ question }) }),
  ragFacts: (id: string, body: FactQuery) => request<FactResult>(`/api/debates/${id}/rag/facts`,
    { method: 'POST', body: JSON.stringify(body) }),
  search: (q: string) => request<{ items: StockItem[] }>(`/api/stocks/search?q=${encodeURIComponent(q)}`),
  stock: (ticker: string) => request<StockDetail>(`/api/stocks/${ticker}`),
  createDebate: (ticker: string) =>
    request<Debate>('/api/debates', { method: 'POST', body: JSON.stringify({ ticker }) }),
  debate: (id: string) => request<Debate>(`/api/debates/${id}`),
  submitJudgment: (
    id: string,
    body: { decision: Decision; confidence: number; evidencePicks: string[]; memo: string | null },
  ) => request<Reveal>(`/api/debates/${id}/judgment`, { method: 'POST', body: JSON.stringify(body) }),
  reveal: (id: string) => request<Reveal>(`/api/debates/${id}/reveal`),
  chart: (id: string) => request<Chart>(`/api/debates/${id}/chart`),
  quizStart: () => request<QuizRound>('/api/quiz/rounds', { method: 'POST' }),
  quizRound: (id: string) => request<QuizRound>(`/api/quiz/rounds/${id}`),
  quizStats: () => request<QuizStats>('/api/quiz/stats'),
  report: (all: boolean) => request<Report>(`/api/report?scope=${all ? 'all' : 'official'}`),
  quizAnswer: (id: string, idx: number, decision: Decision) =>
    request<QuizAnswer>(`/api/quiz/rounds/${id}/questions/${idx}/answer`, { method: 'POST', body: JSON.stringify({ decision }) }),
  quizRanking: (all: boolean) => request<Ranking>(`/api/quiz/ranking?scope=${all ? 'all' : 'today'}`),
  me: () => request<Me>('/api/me'),
  kakaoConfig: () => request<{ enabled: boolean; clientId: string | null }>('/api/auth/kakao/config'),
  kakaoLogin: (code: string, redirectUri: string) =>
    request<{ userId: string; token: string; merged: boolean }>('/api/auth/kakao', { method: 'POST', body: JSON.stringify({ code, redirectUri }) }),
  deleteMe: () => request<void>('/api/me', { method: 'DELETE' }),
  setNickname: (nickname: string) => request<Me>('/api/me/nickname', { method: 'PUT', body: JSON.stringify({ nickname }) }),
  myJudgments: () => request<{ items: JudgmentView[] }>('/api/me/judgments'),
  myJudgment: (id: string) => request<JudgmentDetail>(`/api/me/judgments/${id}`),
  myStats: () => request<MyStats>('/api/me/stats'),
  feed: () => request<{ dataDate: string | null; items: FeedItem[] }>('/api/feed'),
}

/** EventSource는 헤더를 못 붙여서 토큰을 쿼리로 보낸다. 재연결 시 Last-Event-ID는 브라우저가 붙인다. */
export async function debateStreamUrl(id: string): Promise<string> {
  const token = await ensureToken()
  return `${API_BASE}/api/debates/${id}/stream?access_token=${encodeURIComponent(token)}`
}
