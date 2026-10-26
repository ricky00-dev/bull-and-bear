import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { api } from '../lib/api'
import { monthDay } from '../lib/format'
import type { FeedItem } from '../lib/types'
import { Icon } from './ui'
import { ICONS } from './icons'

/**
 * 홈 "오늘의 토론". 검색하지 않아도 바로 볼 수 있고, 전부 같은 데이터로 이미 진행된 토론이라 기다리지 않는다.
 * 진행 중인 토론이 있으면 끝날 때까지 자주 새로 고친다.
 */
const FOLDED = 5

export function TodayFeed() {
  const [expanded, setExpanded] = useState(false)
  const feed = useQuery({
    queryKey: ['feed'],
    queryFn: api.feed,
    staleTime: 30_000,
    refetchInterval: (q) => (q.state.data?.items.some((i) => i.status === 'RUNNING') ? 10_000 : 60_000),
  })
  const data = feed.data
  if (!data || data.items.length === 0 || !data.dataDate) return null

  return (
    <section className="flex flex-col gap-2.5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-[17px] font-extrabold">오늘의 토론</h2>
        <span className="text-xs text-sub">{monthDay(data.dataDate)} 종가 기준 · 바로 볼 수 있어요</span>
      </div>
      <ul className="flex flex-col gap-2">
        {(expanded ? data.items : data.items.slice(0, FOLDED)).map((item) => (
          <li key={item.debateId}>
            <FeedCard item={item} />
          </li>
        ))}
      </ul>
      {!expanded && data.items.length > FOLDED && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="min-h-11 rounded-xl border border-line bg-white text-sm font-bold text-sub"
        >
          {data.items.length - FOLDED}개 더 보기
        </button>
      )}
    </section>
  )
}

function FeedCard({ item }: { item: FeedItem }) {
  // 이미 판정했으면 결과 화면으로, 아니면 토론부터
  const to = item.mine ? `/debates/${item.debateId}/reveal` : `/debates/${item.debateId}`
  const running = item.status === 'RUNNING'
  return (
    <Link to={to} className="flex min-h-16 items-center gap-3 rounded-2xl border border-line bg-white px-4 py-3">
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-[15px] font-bold">{item.stockName}</span>
          {running && (
            <span className="flex shrink-0 items-center gap-1 rounded-md bg-up-soft px-1.5 py-0.5 text-[11px] font-bold text-up-ink">
              <span className="animate-pulse-dot size-1.5 rounded-full bg-up" />
              토론 중
            </span>
          )}
          {item.scheduled && !running && (
            <span className="shrink-0 rounded-md bg-mod-soft px-1.5 py-0.5 text-[11px] font-bold text-mod-ink">매일 토론</span>
          )}
        </span>
        <span className="text-xs text-sub">
          {item.ticker} · {item.judged > 0 ? `${item.judged}명 판정` : '아직 판정한 사람이 없어요'}
        </span>
      </span>
      <span className={`shrink-0 text-[13px] font-bold ${item.mine ? 'text-sub' : 'text-ink'}`}>
        {item.mine ? '내 결과' : running ? '보러 가기' : '판정하기'}
      </span>
      <Icon d={ICONS.chevron} size={16} className="shrink-0 text-faint" />
    </Link>
  )
}
