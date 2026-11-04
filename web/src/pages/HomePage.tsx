import { useQuery } from '@tanstack/react-query'
import { useDeferredValue, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { IntroSheet } from '../components/IntroSheet'
import { TabBar } from '../components/TabBar'
import { TodayFeed } from '../components/TodayFeed'
import { TodayTerm } from '../components/TodayTerm'
import { Icon, Logo, Screen } from '../components/ui'
import { ICONS } from '../components/icons'
import { api } from '../lib/api'
import { changeColor, dueLabel, pct, won } from '../lib/format'
import { isPending } from '../lib/score'
import { DECISION_LABEL } from '../lib/types'
import type { StockItem } from '../lib/types'

const RECENT_KEY = 'bb.recent'
const SUGGESTIONS = [
  { name: '삼성전자', ticker: '005930', market: 'KOSPI' },
  { name: 'SK하이닉스', ticker: '000660', market: 'KOSPI' },
  { name: '카카오', ticker: '035720', market: 'KOSPI' },
  { name: '현대차', ticker: '005380', market: 'KOSPI' },
  { name: '에코프로비엠', ticker: '247540', market: 'KOSDAQ' },
]

function loadRecent(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]') as string[]
  } catch {
    return []
  }
}

function saveRecent(name: string) {
  try {
    const next = [name, ...loadRecent().filter((n) => n !== name)].slice(0, 6)
    localStorage.setItem(RECENT_KEY, JSON.stringify(next))
  } catch {
    // 저장 못 해도 검색은 된다
  }
}

export function HomePage() {
  const [query, setQuery] = useState('')
  const deferred = useDeferredValue(query.trim())
  const navigate = useNavigate()
  const recent = loadRecent()

  const search = useQuery({
    queryKey: ['search', deferred],
    queryFn: () => api.search(deferred),
    enabled: deferred.length > 0,
    staleTime: 60_000,
  })

  const open = (s: StockItem) => {
    saveRecent(s.name)
    navigate(`/stocks/${s.ticker}`)
  }

  // 진행 중인 내 판정 (채점 대기) 중 가장 최근 것
  const mine = useQuery({ queryKey: ['me', 'judgments'], queryFn: api.myJudgments, staleTime: 60_000 })
  const pending = mine.data?.items.find(isPending)
  const nextScore = pending?.scores.find((s) => s.status === 'PENDING')

  // 피드에 이미 있는 종목은 "종목을 골라 시작하기"에서 뺀다 (같은 종목이 두 번 보이지 않게)
  const feed = useQuery({ queryKey: ['feed'], queryFn: api.feed, staleTime: 30_000 })
  const inFeed = new Set(feed.data?.items.map((i) => i.ticker))
  const suggestions = SUGGESTIONS.filter((s) => !inFeed.has(s.ticker))

  const items = search.data?.items ?? []
  const eligibleCount = items.filter((i) => i.eligible).length

  return (
    <Screen wide>
      <header className="pt-safe px-5">
        <div className="flex items-center justify-between pb-2 pt-5">
          <div className="md:invisible">
            <Logo />
          </div>
          <Link to="/my" className="pressable flex min-h-touch items-center rounded-control px-3 text-sm text-sub">게스트</Link>
        </div>
      </header>

      <div className="flex flex-col gap-3 px-5 pb-5 pt-3 md:max-w-[560px]">
        <h1 className="text-2xl font-extrabold leading-snug tracking-tight">
          어떤 종목을
          <br />
          판정해 볼까요?
        </h1>
        <p className="text-sm leading-relaxed text-sub">
          <b className="text-up">매수</b>와 <b className="text-down">매도</b>의 근거를 읽고, AI보다 먼저 판정해요.
        </p>
        <label
          className={`flex min-h-14 items-center gap-2 rounded-control border bg-white pl-4 pr-1.5 transition-colors focus-within:border-ink focus-within:ring-1 focus-within:ring-ink ${query ? 'border-ink' : 'border-line'}`}
        >
          <Icon d={ICONS.search} className="text-sub" />
          <span className="sr-only">종목 검색</span>
          <input
            value={query}
            type="search"
            onChange={(e) => setQuery(e.target.value)}
            placeholder="종목명·코드·초성으로 검색"
            autoComplete="off"
            enterKeyHint="search"
            className="min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-faint"
          />
          {query && (
            <button
              type="button"
              aria-label="검색어 지우기"
              onClick={() => setQuery('')}
              className="pressable flex size-touch items-center justify-center rounded-control text-sub"
            >
              <Icon d={ICONS.close} size={14} stroke={2.5} />
            </button>
          )}
        </label>
      </div>

      <main className="flex flex-1 flex-col gap-6 px-5 pb-8">
        {!deferred && (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] lg:items-start lg:gap-8">
            <div className="flex min-w-0 flex-col gap-5">
              {pending && nextScore && (
                <Link
                  to={`/me/judgments/${pending.judgmentId}`}
                  className="flex items-center justify-between gap-3 rounded-2xl bg-ink p-4 text-white"
                >
                  <span className="flex flex-col gap-1">
                    <span className="text-xs text-[#c9cdd6]">진행 중인 내 판정</span>
                    <span className="text-[15px] font-bold">
                      {pending.stockName} · {DECISION_LABEL[pending.decision]} · {nextScore.horizonDays}거래일 {dueLabel(nextScore.scheduledDate)}
                    </span>
                  </span>
                  <Icon d={ICONS.chevron} />
                </Link>
              )}
              <TodayFeed />
              {suggestions.length > 0 && <section className="flex flex-col gap-3">
                <h2 className="text-base font-bold">종목을 골라 시작하기</h2>
                <ul className="overflow-hidden rounded-panel border border-line bg-white">
                  {suggestions.map((s) => (
                    <li key={s.ticker} className="border-b border-line-soft last:border-0">
                      <Link
                        to={`/stocks/${s.ticker}`}
                        onClick={() => saveRecent(s.name)}
                        className="pressable flex min-h-16 items-center gap-3 px-4 py-3 transition-colors"
                      >
                        <span className="flex min-w-0 flex-1 flex-col gap-1">
                          <span className="text-[15px] font-bold">{s.name}</span>
                          <span className="text-[13px] text-sub">{s.ticker} · {s.market}</span>
                        </span>
                        <span className="text-sm text-sub">살펴보기</span>
                        <Icon d={ICONS.chevron} size={16} className="text-sub" />
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>}
              {recent.length > 0 && (
                <ChipRow title="최근 검색" items={recent} onPick={setQuery} />
              )}
            </div>
            <div className="flex min-w-0 flex-col gap-6">
              <TodayTerm />
              <Link to="/quiz" className="pressable flex min-h-touch items-center justify-between gap-3 rounded-panel border border-line bg-white p-4 transition-colors">
                <span className="text-sm font-bold">결과를 아는 과거 종목으로 연습하기</span>
                <Icon d={ICONS.chevron} size={18} className="shrink-0 text-sub" />
              </Link>
              <p className="text-[13px] leading-relaxed text-sub">
                모의·교육 서비스예요. AI 판정은 투자 권유가 아니에요.
              </p>
            </div>
          </div>
        )}

        {deferred && (
          <div className="flex flex-col gap-2.5">
            <p className="text-[13px] text-sub" aria-live="polite">
              {search.fetchStatus === 'paused' ? '연결을 기다리고 있어요' : search.isFetching || query.trim() !== deferred ? '찾는 중…' : search.isError ? '검색을 완료하지 못했어요' : `토론할 수 있는 종목 ${eligibleCount}개 · 우선주·ETF 제외`}
            </p>
            {(search.isError || search.fetchStatus === 'paused') && (
              <div role="alert" className="flex flex-col items-start gap-2 rounded-panel border border-line bg-white p-4">
                <p className="text-sm">{search.fetchStatus === 'paused' ? '네트워크 연결을 확인해 주세요. 연결되면 검색을 다시 시작해요.' : '종목을 불러오지 못했어요. 연결을 확인하고 다시 시도해 주세요.'}</p>
                {search.fetchStatus !== 'paused' && <button type="button" onClick={() => search.refetch()} className="pressable min-h-touch rounded-control border border-line px-4 text-sm font-bold">다시 시도</button>}
              </div>
            )}
            {items.length > 0 && (
              <ul className="overflow-hidden rounded-2xl border border-line bg-white">
                {items.map((s) => (
                  <li key={s.ticker} className="border-b border-line-soft last:border-0">
                    {s.eligible ? (
                      <button type="button" onClick={() => open(s)} className="pressable flex min-h-16 w-full items-center gap-3 px-4 py-2.5 text-left transition-colors">
                        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                          <Highlighted text={s.name} query={deferred} />
                          <span className="text-xs text-sub">
                            {s.ticker} · {s.market}
                          </span>
                        </span>
                        <Price close={s.close} change={s.changePct} />
                      </button>
                    ) : (
                      <div className="flex min-h-16 items-center gap-3 bg-[#fafafb] px-4 py-2.5">
                        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                          <span className="text-[15px] text-sub">{s.name}</span>
                          <span className="text-xs text-sub">
                            {s.ticker} · {s.blockReason}
                          </span>
                        </span>
                        <span className="rounded-md bg-line px-2 py-1 text-[11px] font-bold text-sub">토론 불가</span>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {search.isSuccess && !search.isFetching && items.length === 0 && (
              <div className="flex flex-col gap-1.5 py-8 text-center">
                <p className="text-[15px] font-bold">'{deferred}'에 맞는 종목이 없어요</p>
                <p className="text-[13px] text-sub">종목명 일부, 6자리 코드, 초성으로 찾아보세요</p>
              </div>
            )}
          </div>
        )}
      </main>
      <TabBar />
      <IntroSheet />
    </Screen>
  )
}

function ChipRow({ title, items, onPick }: { title: string; items: string[]; onPick: (v: string) => void }) {
  return (
    <section className="flex flex-col gap-2.5">
      <h2 className="text-[13px] font-bold text-sub">{title}</h2>
      <div className="flex flex-wrap gap-2">
        {items.map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => onPick(name)}
            className="pressable min-h-touch rounded-control border border-line bg-white px-3.5 text-sm transition-colors"
          >
            {name}
          </button>
        ))}
      </div>
    </section>
  )
}

/** 검색어와 맞는 부분을 강조 (초성 검색이면 강조 없음) */
function Highlighted({ text, query }: { text: string; query: string }) {
  const i = text.indexOf(query)
  if (i < 0) return <span className="text-[15px] font-medium">{text}</span>
  return (
    <span className="text-[15px] font-medium">
      {text.slice(0, i)}
      <strong className="font-extrabold underline decoration-line underline-offset-4">{query}</strong>
      {text.slice(i + query.length)}
    </span>
  )
}

function Price({ close, change }: { close: number; change: number }) {
  return (
    <span className="flex flex-col items-end gap-0.5">
      <span className="text-sm font-bold">{won(close)}</span>
      <span className={`text-xs font-bold ${changeColor(change)}`}>{pct(change)}</span>
    </span>
  )
}
