// 전시장 관람객 한 명의 흐름을 흉내 낸다. 새 토론 시작(LLM 호출)은 하지 않는다.
// 테스트 게스트는 닉네임을 k6t_로 시작하게 해서 끝나고 지운다.
import http from 'k6/http'
import { check, sleep, group } from 'k6'

const BASE = __ENV.BASE || 'https://54-253-242-203.sslip.io'
const PEAK = Number(__ENV.PEAK || 30)
const FALLBACK_DEBATE = 'd1462b74-79cf-43c2-8dc4-1838dc643819'

export const options = {
  scenarios: {
    visitors: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: Math.ceil(PEAK / 3) },
        { duration: '1m', target: PEAK },
        { duration: '2m', target: PEAK },
        { duration: '20s', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
    // 전시장 노트북: 랭킹 15초, 판정 수 30초마다
    exhibit: {
      executor: 'constant-vus', vus: 1, duration: '3m50s', exec: 'exhibit',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{kind:read}': ['p(95)<800'],
    // API별 시간을 결과에 따로 보이게 하려는 기준 (넉넉하게)
    ...Object.fromEntries(['guest', 'nickname', 'feed', 'search', 'debate', 'stream', 'chart', 'quiz_start',
      'quiz_round', 'quiz_answer', 'ranking', 'exhibit_ranking', 'exhibit_feed']
      .map((n) => [`http_req_duration{name:${n}}`, ['p(95)<3000']])),
  },
}

const read = { tags: { kind: 'read' } }

function auth(token, extra = {}) {
  return { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, ...extra }
}

function guest() {
  const res = http.post(`${BASE}/api/auth/guest`, null, { tags: { kind: 'write', name: 'guest' } })
  check(res, { 'guest 200': (r) => r.status === 200 || r.status === 201 })
  const token = res.json('token')
  http.put(`${BASE}/api/me/nickname`, JSON.stringify({ nickname: `k6t_${String(__VU).padStart(3, '0')}${__ITER % 10}` }),
    auth(token, { tags: { kind: 'write', name: 'nickname' } }))
  return token
}

export default function () {
  const token = guest()
  let debateId = FALLBACK_DEBATE

  group('home', () => {
    const feed = http.get(`${BASE}/api/feed`, auth(token, { ...read, tags: { kind: 'read', name: 'feed' } }))
    check(feed, { 'feed 200': (r) => r.status === 200 })
    const items = feed.json('items') || []
    if (items.length) debateId = items[Math.floor(Math.random() * items.length)].debateId
  })
  sleep(1 + Math.random() * 2)

  group('search', () => {
    const r = http.get(`${BASE}/api/stocks/search?q=${encodeURIComponent('삼성')}&limit=10`,
      auth(token, { tags: { kind: 'read', name: 'search' } }))
    check(r, { 'search 200': (x) => x.status === 200 })
  })
  sleep(1 + Math.random() * 2)

  group('debate', () => {
    const d = http.get(`${BASE}/api/debates/${debateId}`, auth(token, { tags: { kind: 'read', name: 'debate' } }))
    check(d, { 'debate 200': (r) => r.status === 200 })
    // 끝난 토론은 서버가 처음부터 재생하고 닫는다
    const s = http.get(`${BASE}/api/debates/${debateId}/stream?access_token=${encodeURIComponent(token)}`,
      { headers: { Accept: 'text/event-stream' }, timeout: '30s', tags: { kind: 'stream', name: 'stream' } })
    check(s, { 'stream sealed': (r) => r.status === 200 && r.body.includes('debate_sealed') })
    http.get(`${BASE}/api/debates/${debateId}/chart`, auth(token, { tags: { kind: 'read', name: 'chart' } }))
  })
  sleep(2 + Math.random() * 3)

  group('quiz', () => {
    const start = http.post(`${BASE}/api/quiz/rounds`, null, auth(token, { tags: { kind: 'write', name: 'quiz_start' } }))
    if (!check(start, { 'quiz start 200': (r) => r.status === 200 || r.status === 201 })) return
    const round = start.json('id')
    const total = start.json('total')
    const choices = ['BUY', 'HOLD', 'SELL']
    for (let i = 0; i < total; i++) {
      sleep(2 + Math.random() * 3) // 문제 읽는 시간
      const a = http.post(`${BASE}/api/quiz/rounds/${round}/questions/${i}/answer`,
        JSON.stringify({ decision: choices[Math.floor(Math.random() * 3)] }),
        auth(token, { tags: { kind: 'write', name: 'quiz_answer' } }))
      check(a, { 'answer 200': (r) => r.status === 200 })
      if (i < total - 1) {
        http.get(`${BASE}/api/quiz/rounds/${round}`, auth(token, { tags: { kind: 'read', name: 'quiz_round' } }))
      }
    }
  })

  group('ranking', () => {
    const r = http.get(`${BASE}/api/quiz/ranking?scope=today`, auth(token, { tags: { kind: 'read', name: 'ranking' } }))
    check(r, { 'ranking 200': (x) => x.status === 200 })
  })
  sleep(1)
}

let exhibitToken
export function exhibit() {
  if (!exhibitToken) {
    exhibitToken = http.post(`${BASE}/api/auth/guest`).json('token')
    http.put(`${BASE}/api/me/nickname`, JSON.stringify({ nickname: 'k6t_exh' }), auth(exhibitToken))
  }
  http.get(`${BASE}/api/quiz/ranking?scope=today`, auth(exhibitToken, { tags: { kind: 'read', name: 'exhibit_ranking' } }))
  http.get(`${BASE}/api/feed`, auth(exhibitToken, { tags: { kind: 'read', name: 'exhibit_feed' } }))
  sleep(15)
}
