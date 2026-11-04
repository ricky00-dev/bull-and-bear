import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { api } from '../lib/api'
import { groupFeed } from '../lib/experience'
import { monthDay } from '../lib/format'
import type { FeedItem } from '../lib/types'
import { Icon, Skeleton } from './ui'
import { ICONS } from './icons'

/** 완료된 토론과 아직 진행 중인 토론을 구분해 첫 체험의 기다림을 알린다. */
export function TodayFeed() {
  const feed = useQuery({
    queryKey: ['feed'], queryFn: api.feed, staleTime: 30_000,
    refetchInterval: q => q.state.data?.items.some(i => i.status === 'RUNNING') ? 10_000 : 60_000,
  })
  if (!feed.data && feed.isPending && feed.fetchStatus !== 'paused') return <section aria-label="준비된 토론 확인 중" aria-busy="true" className="flex flex-col gap-3"><h2 className="text-base font-bold">바로 읽을 토론 찾는 중</h2><Skeleton className="h-20 w-full" /></section>
  const groups = groupFeed(feed.data?.items ?? [])
  const unavailable = feed.isError || feed.fetchStatus === 'paused'
  return <div className="flex flex-col gap-5">
    {unavailable && !feed.data ? <section className="flex flex-col gap-3 rounded-panel border border-line bg-white p-4">
      <h2 className="text-base font-bold">준비된 토론을 확인하지 못했어요</h2>
      <p className="text-sm leading-relaxed text-sub">{feed.fetchStatus === 'paused' ? '네트워크 연결을 기다리고 있어요. 연결되면 준비된 토론을 다시 확인해요.' : '연결을 확인하고 다시 시도하거나, 종목을 직접 찾아볼 수 있어요.'}</p>
      {feed.fetchStatus !== 'paused' && <button type="button" onClick={() => feed.refetch()} className="pressable min-h-touch self-start rounded-control border border-line px-3 text-sm font-bold">다시 확인</button>}
    </section> : <FeedGroup title="바로 읽을 수 있는 토론" description="완료된 토론을 읽고 내 판정부터 내려보세요." items={groups.ready} />}
    {groups.ready.length === 0 && !unavailable && <section className="flex flex-col gap-3 rounded-panel border border-line bg-white p-4">
      <h2 className="text-base font-bold">첫 토론을 골라보세요</h2>
      <p className="text-sm leading-relaxed text-sub">아직 완료된 토론이 없어요. 아래에서 종목을 골라 시작하거나, 과거 토론 퀴즈를 확인해 보세요.</p>
      <Link to="/quiz" className="pressable flex min-h-touch items-center justify-between gap-2 rounded-control border border-line px-3 text-sm font-bold">과거 토론으로 먼저 연습<Icon d={ICONS.chevron} size={16} /></Link>
    </section>}
    <FeedGroup title="진행 중인 토론" description="자료 확인과 발언 생성이 진행 중이에요. 먼저 나온 발언부터 읽을 수 있어요." items={groups.running} />
  </div>
}

function FeedGroup({title, description, items}: { title: string; description: string; items: FeedItem[] }) {
  const [expanded, setExpanded] = useState(false)
  if (items.length === 0) return null
  return <section className="flex flex-col gap-3">
    <div className="flex flex-col gap-1"><h2 className="text-base font-bold">{title}</h2><p className="text-[13px] leading-relaxed text-sub">{description}</p></div>
    <ul className="flex flex-col gap-2">{(expanded ? items : items.slice(0,3)).map(item => <li key={item.debateId}><FeedCard item={item} /></li>)}</ul>
    {items.length > 3 && <button type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded} className="pressable min-h-touch rounded-control border border-line bg-white text-sm font-medium">{expanded ? '접기' : `${items.length-3}개 더 보기`}</button>}
  </section>
}

function FeedCard({item}: {item: FeedItem}) {
  const running = item.status === 'RUNNING'
  const to = item.mine ? `/debates/${item.debateId}/reveal` : `/debates/${item.debateId}`
  return <Link to={to} className="pressable flex min-h-20 items-center gap-3 rounded-panel border border-line bg-white px-4 py-3 transition-colors">
    <span className="flex min-w-0 flex-1 flex-col gap-1">
      <span className="text-[15px] font-bold">{item.stockName}</span>
      <span className="text-xs leading-relaxed text-sub">{item.ticker} · {monthDay(item.dataDate)} 종가 기준{running ? ' · 진행 중' : ''}</span>
    </span>
    <span className="shrink-0 text-[13px] font-bold">{item.mine ? '내 결과' : running ? '진행 보기' : '토론 읽기'}</span>
    <Icon d={ICONS.chevron} size={16} className="shrink-0 text-sub" />
  </Link>
}
