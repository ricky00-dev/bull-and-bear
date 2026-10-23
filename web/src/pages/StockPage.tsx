import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router'
import { Sparkline } from '../components/Sparkline'
import { BottomBar, Card, ErrorNotice, Icon, PrimaryButton, Screen, Skeleton, TopBar } from '../components/ui'
import { ICONS } from '../components/icons'
import { api, ApiError } from '../lib/api'
import { changeColor, pct, won } from '../lib/format'
import type { StockDetail } from '../lib/types'

export function StockPage() {
  const { ticker = '' } = useParams()
  const navigate = useNavigate()
  const stock = useQuery({ queryKey: ['stock', ticker], queryFn: () => api.stock(ticker) })
  const start = useMutation({
    mutationFn: () => api.createDebate(ticker),
    onSuccess: (d) => navigate(`/debates/${d.id}`),
  })

  if (stock.isError) {
    return (
      <Screen>
        <TopBar title="종목" back="/" />
        <ErrorNotice message="종목 정보를 불러오지 못했어요" onRetry={() => stock.refetch()} />
      </Screen>
    )
  }

  const s = stock.data
  const today = s?.todayDebate
  const startError = start.error instanceof ApiError ? start.error.message : start.error ? '토론을 시작하지 못했어요' : null
  const blocked = quotaBlock(s?.quota)

  return (
    <Screen>
      <TopBar title={s?.name ?? ''} sub={s ? `${s.ticker} · ${s.market}` : undefined} back="/" />
      <main className="flex flex-1 flex-col gap-3.5 px-5 pb-5 pt-1">
        {!s ? (
          <>
            <Skeleton className="h-16 w-48" />
            <Skeleton className="h-40 w-full" />
          </>
        ) : (
          <>
            <div className="flex flex-col gap-0.5">
              <p className="text-3xl font-extrabold tracking-tight">{won(s.close)}</p>
              <p className={`text-sm font-bold ${changeColor(s.changePct)}`}>
                {pct(s.changePct)} <span className="font-medium text-sub">{s.asOf.slice(5).replace('-', '/')} 종가</span>
              </p>
            </div>
            <Card className="pb-2.5">
              <Sparkline closes={s.sparkline} />
            </Card>

            {!s.eligible && (
              <Card className="border-up-line bg-up-soft">
                <p className="text-sm font-bold text-up-ink">이 종목은 토론할 수 없어요</p>
                <p className="mt-1 text-sm text-up-ink">{s.reasons.join(', ')}</p>
              </Card>
            )}

            <Card className="flex flex-col gap-3">
              <h2 className="text-sm font-extrabold">AI가 근거로 쓸 데이터</h2>
              <DataRow ok label="시세 지표" detail="수익률·이동평균·변동성·거래량" />
              <DataRow label="재무제표" detail="DART · 워커 연동 후" />
              <DataRow label="공시" detail="최근 90일 · 워커 연동 후" />
              <DataRow label="뉴스" detail="최근 7일 · 워커 연동 후" />
              <p className="border-t border-line-soft pt-2 text-xs leading-relaxed text-sub">
                토론을 시작하는 순간 이 데이터를 고정해요. 두 AI는 고정된 데이터만 근거로 쓰고, 모든 수치는 원본과 대조해 검증해요.
              </p>
            </Card>

            {today && (
              <div className="flex items-center gap-3 rounded-2xl border border-mod-line bg-mod-soft px-4 py-3.5">
                <Icon d={ICONS.clock} className="shrink-0 text-mod" />
                <p className="text-[13px] leading-normal text-mod-ink">
                  오늘 {new Date(today.createdAt).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}에 진행된
                  토론이 있어요. 같은 데이터라 바로 볼 수 있어요.
                </p>
              </div>
            )}
          </>
        )}
      </main>

      <BottomBar>
        {startError && <p className="text-[13px] font-bold text-up-ink">{startError}</p>}
        {today ? (
          <PrimaryButton onClick={() => navigate(`/debates/${today.id}`)}>오늘 토론 보기</PrimaryButton>
        ) : (
          <PrimaryButton disabled={!s?.eligible || !!blocked || start.isPending} onClick={() => start.mutate()}>
            {start.isPending ? '토론 준비 중…' : 'AI 토론 시작'}
          </PrimaryButton>
        )}
        <p className="text-center text-xs text-sub">
          {today ? '이미 끝난 토론은 처음부터 다시 볼 수 있어요' : (blocked ?? quotaHint(s?.quota))}
        </p>
      </BottomBar>
    </Screen>
  )
}

/** 새 토론을 시작할 수 없는 이유. 오늘 다른 사람이 시작한 토론은 여전히 볼 수 있다 */
function quotaBlock(q: StockDetail['quota'] | undefined): string | null {
  if (!q) return null
  if (!q.budgetOpen) return '오늘 준비한 AI 토론이 모두 소진됐어요. 내일 다시 열려요'
  if (q.left === 0) return `새 토론은 하루 ${q.limit}번까지예요. 내일 다시 시작할 수 있어요`
  return null
}

function quotaHint(q: StockDetail['quota'] | undefined): string {
  return q ? `1~2분 걸려요 · 오늘 ${q.left}번 더 시작할 수 있어요` : '1~2분 걸려요'
}

function DataRow({ ok = false, label, detail }: { ok?: boolean; label: string; detail: string }) {
  return (
    <div className="flex items-center gap-2.5 text-sm">
      <span
        className={`flex size-5.5 items-center justify-center rounded-full ${ok ? 'bg-ok-soft text-ok' : 'bg-line-soft text-sub'}`}
        aria-label={ok ? '준비됨' : '대기'}
      >
        {ok ? <Icon d={ICONS.check} size={12} stroke={3} /> : <span className="text-xs">–</span>}
      </span>
      <span className="flex-1">{label}</span>
      <span className="text-xs text-sub">{detail}</span>
    </div>
  )
}
