import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { NicknameForm } from '../components/NicknameForm'
import { Card, ErrorNotice, Screen, Skeleton, TopBar } from '../components/ui'
import { api, myName } from '../lib/api'
import type { RankEntry } from '../lib/types'

/**
 * 타임머신 퀴즈 랭킹. 전시장에서는 "오늘"이 기본: 그날 온 관람객끼리 겨룬다.
 * 맞힌 문제 수 → 덜 풀고 맞힌 사람 → 먼저 도달한 사람 순.
 */
export function RankingPage() {
  const [all, setAll] = useState(false)
  const q = useQuery({ queryKey: ['ranking', all], queryFn: () => api.quizRanking(all), refetchInterval: 30_000 })
  const r = q.data
  const mineInTop = r?.top.some((e) => e.me)

  return (
    <Screen>
      <TopBar title="퀴즈 랭킹" sub={r ? `${r.players}명 참여` : undefined} back="/quiz" />
      <main className="flex flex-1 flex-col gap-3.5 px-5 pb-6">
        <div className="grid grid-cols-2 gap-2">
          <Toggle on={!all} onClick={() => setAll(false)}>
            오늘
          </Toggle>
          <Toggle on={all} onClick={() => setAll(true)}>
            전체
          </Toggle>
        </div>

        <NicknameCard />

        {q.isError && <ErrorNotice message="랭킹을 불러오지 못했어요" onRetry={() => q.refetch()} />}
        {!r && !q.isError && <Skeleton className="h-72 w-full" />}
        {r && r.top.length === 0 && (
          <Card className="flex flex-col items-center gap-2 py-8 text-center">
            <p className="text-[17px] font-extrabold">{all ? '아직 아무도 퀴즈를 풀지 않았어요' : '오늘 첫 번째 도전자가 되어 보세요'}</p>
            <Link to="/quiz" className="text-sm font-bold text-point">
              퀴즈 풀러 가기
            </Link>
          </Card>
        )}
        {r && r.top.length > 0 && (
          <div className="overflow-hidden rounded-2xl bg-surface">
            <ol>
              {r.top.map((e, i) => (
                <Row key={i} e={e} />
              ))}
            </ol>
            {r.mine && !mineInTop && (
              <div className="border-t-2 border-dashed border-line">
                <Row e={r.mine} />
              </div>
            )}
          </div>
        )}
        {r && !r.mine && r.top.length > 0 && (
          <Link to="/quiz" className="text-center text-sm font-bold text-point">
            퀴즈를 풀면 나도 랭킹에 올라가요
          </Link>
        )}

        <p className="text-[11px] leading-relaxed text-sub">
          맞힌 문제 수로 순위를 매기고, 같으면 더 적게 풀고 맞힌 사람이 위예요. 오늘 랭킹은 한국 시간 자정에 새로 시작해요.
        </p>
      </main>
    </Screen>
  )
}

function Row({ e }: { e: RankEntry }) {
  const medal = e.rank <= 3 ? ['🥇', '🥈', '🥉'][e.rank - 1] : null
  return (
    <li className={`flex min-h-14 items-center gap-3 border-b border-line-soft px-4 py-2.5 last:border-b-0 ${e.me ? 'bg-mod-soft' : ''}`}>
      <span className="w-8 shrink-0 text-center text-[15px] font-extrabold">{medal ?? e.rank}</span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className={`truncate text-[15px] font-bold ${e.me ? 'text-mod' : ''}`}>
          {e.name}
          {e.me && <span className="ml-1 text-xs">(나)</span>}
        </span>
        <span className="text-xs text-sub">
          {e.answered}문제 중 · 적중률 {Math.round((e.hits / e.answered) * 100)}%
        </span>
      </span>
      <span className="flex items-baseline gap-0.5">
        <span className="text-lg font-extrabold">{e.hits}</span>
        <span className="text-[11px] text-sub">맞힘</span>
      </span>
    </li>
  )
}

/** 랭킹에 보일 이름. 정하지 않으면 "게스트 #abcd"(가입자는 "회원 #abcd")로 보인다 */
function NicknameCard() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const [editing, setEditing] = useState(false)
  if (!me.data) return null
  const current = me.data.nickname

  if (!editing) {
    return (
      <div className="flex items-center justify-between rounded-2xl bg-surface px-4 py-3">
        <span className="flex flex-col">
          <span className="text-xs text-sub">랭킹에 보일 내 이름</span>
          <span className="text-[15px] font-extrabold">{current ?? myName(me.data)}</span>
        </span>
        <button type="button" onClick={() => setEditing(true)} className="min-h-10 rounded-xl bg-surface-2 px-3.5 text-[13px] font-bold">
          {current ? '바꾸기' : '닉네임 정하기'}
        </button>
      </div>
    )
  }
  return <NicknameForm initial={current ?? ''} onDone={() => setEditing(false)} className="rounded-panel bg-surface p-4 point-ring" />
}

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={`min-h-10 rounded-xl px-3.5 text-[13px] font-bold ${on ? 'bg-point text-on-point' : 'bg-surface-2 text-sub'}`}
    >
      {children}
    </button>
  )
}
