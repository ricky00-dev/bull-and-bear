import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { VerdictText } from '../components/VerdictText'
import { BottomBar, Card, ErrorNotice, Icon, PrimaryButton, Screen, Skeleton, TopBar } from '../components/ui'
import { ICONS } from '../components/icons'
import { api, ApiError } from '../lib/api'
import { describe } from '../lib/glossary'
import type { Score } from '../lib/types'
import { JudgmentComparison } from '../components/JudgmentComparison'
import { EvidenceComparison } from '../components/EvidenceComparison'
import { useDebateStream } from '../lib/useDebateStream'

const RUBRIC: { key: keyof Omit<Score, 'comment'>; label: string }[] = [
  { key: 'relevance', label: '관련성' },
  { key: 'materiality', label: '중요도' },
  { key: 'rebuttal', label: '반박' },
  { key: 'risk_awareness', label: '리스크 인식' },
]

export function RevealPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const debate = useQuery({ queryKey: ['debate', id], queryFn: () => api.debate(id) })
  const reveal = useQuery({ queryKey: ['reveal', id], queryFn: () => api.reveal(id), retry: false })
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const mineId = reveal.data?.mine.id
  const detail = useQuery({ queryKey: ['me', 'judgment', mineId], queryFn: () => api.myJudgment(mineId!), enabled: !!mineId })
  const schedule = detail.data?.judgment.scores ?? []
  const stream = useDebateStream(reveal.data ? id : undefined)

  // 아직 판정하지 않았으면 판정 화면으로 (봉인)
  const sealed = reveal.error instanceof ApiError && reveal.error.code === 'SEALED'
  useEffect(() => {
    if (sealed) navigate(`/debates/${id}/judge`, { replace: true })
  }, [sealed, id, navigate])

  const r = reveal.data
  const d = debate.data

  if (reveal.isError && !sealed) {
    return (
      <Screen>
        <TopBar title="판정 결과" back="/" />
        <ErrorNotice message="결과를 불러오지 못했어요" onRetry={() => reveal.refetch()} />
      </Screen>
    )
  }

  return (
    <Screen wide>
      <TopBar title={d?.stockName ?? '판정 결과'} sub="판정 결과" back={`/debates/${id}`} />
      <main className="flex flex-1 flex-col gap-3.5 px-5 pb-6 pt-1">
        {!r ? (
          <>
            <Skeleton className="h-10 w-56" />
            <Skeleton className="h-28 w-full" />
            <Skeleton className="h-40 w-full" />
          </>
        ) : (
          <>
            <div className="flex flex-col gap-1">
              <p className="text-[13px] font-bold text-mod">AI 판정 공개</p>
              <h2 className="text-2xl font-extrabold tracking-tight">{r.agrees ? 'AI와 같은 판정이에요' : 'AI와 판정이 엇갈렸어요'}</h2>
            </div>

            <JudgmentComparison mine={r.mine.decision} moderator={r.verdict.decision} scores={schedule} holdBand={detail.data?.holdBand} loading={detail.isLoading} error={detail.isError} onRetry={() => detail.refetch()} />
            <p className="text-[13px] leading-relaxed text-sub">확신: 나 {r.mine.confidence}% / AI {Math.round(r.verdict.confidence * 100)}%. 판정의 일치와 실제 적중은 달라요.</p>
            <EvidenceComparison mine={r.mine.evidencePicks} decisive={r.verdict.decisive_evidence} turns={stream.statements} asOf={d?.tradeDate} debateId={id} memo={r.mine.memo} />

            <Crowd crowd={r.crowd} />

            <Card className="flex flex-col gap-2.5">
              <h3 className="text-sm font-extrabold">중재자가 이렇게 본 이유</h3>
              <p className="text-[15px] leading-relaxed">
                <VerdictText text={r.verdict.reasoning} decisive={r.verdict.decisive_evidence} debateId={id} asOf={d?.tradeDate} turns={stream.statements} />
              </p>
              <div className="flex flex-wrap gap-1.5">
                {r.verdict.decisive_evidence.map((id) => (
                  <span key={id} className="rounded-lg bg-ground px-2.5 py-1.5 text-xs font-bold">
                    결정적 · {describe(id).label}
                  </span>
                ))}
              </div>
            </Card>

            <Card className="flex flex-col gap-3">
              <div className="flex justify-between text-xs font-extrabold">
                <span className="text-up-ink">매수 측</span>
                <span className="text-sub">기준표 (5점)</span>
                <span className="text-down-ink">매도 측</span>
              </div>
              {RUBRIC.map(({ key, label }) => (
                <div key={key} className="grid grid-cols-[1fr_88px_1fr] items-center gap-2">
                  <div className="flex items-center justify-end gap-1.5">
                    <span className="text-xs font-extrabold">{r.verdict.scores.bull[key]}</span>
                    <span className="h-2 rounded-full bg-up" style={{ width: r.verdict.scores.bull[key] * 14 }} />
                  </div>
                  <span className="text-center text-xs text-sub">{label}</span>
                  <div className="flex items-center gap-1.5">
                    <span className="h-2 rounded-full bg-down" style={{ width: r.verdict.scores.bear[key] * 14 }} />
                    <span className="text-xs font-extrabold">{r.verdict.scores.bear[key]}</span>
                  </div>
                </div>
              ))}
            </Card>

            <Link to={`/me/judgments/${r.mine.id}`} className="pressable flex min-h-touch items-center justify-between rounded-control border border-line bg-white px-4 py-3 text-sm font-bold">
              내 판정에서 채점 결과 보기 <Icon d={ICONS.chevron} size={16} />
            </Link>

            {me.data?.guest && <SignupCard />}
            <p className="text-center text-[11px] leading-relaxed text-sub">
              교육용 모의 판정이에요. AI 판정은 투자 권유가 아니에요.
            </p>
          </>
        )}
      </main>
      <BottomBar>
        <PrimaryButton variant="outline" onClick={() => navigate('/')}>
          다른 종목 판정하기
        </PrimaryButton>
      </BottomBar>
    </Screen>
  )
}

/** 내 판정을 낸 뒤에만 보여준다. 미리 보면 남의 판단에 끌려가기 쉽다. */
function Crowd({ crowd }: { crowd: { buy: number; hold: number; sell: number; total: number } }) {
  const share = (n: number) => (crowd.total ? Math.round((n / crowd.total) * 100) : 0)
  return (
    <Card className="flex flex-col gap-2.5">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-extrabold">이 토론을 본 사람들</h3>
        <span className="text-[11px] text-sub">{crowd.total}명</span>
      </div>
      <div className="flex h-3 gap-0.5 overflow-hidden rounded-full bg-line" role="img" aria-label={`매수 ${share(crowd.buy)}%, 보류 ${share(crowd.hold)}%, 매도 ${share(crowd.sell)}%`}>
        <span className="bg-up" style={{ width: `${share(crowd.buy)}%` }} />
        <span className="bg-faint" style={{ width: `${share(crowd.hold)}%` }} />
        <span className="bg-down" style={{ width: `${share(crowd.sell)}%` }} />
      </div>
      <div className="flex justify-between text-xs font-bold">
        <span className="text-up-ink">매수 {share(crowd.buy)}%</span>
        <span className="text-sub">보류 {share(crowd.hold)}%</span>
        <span className="text-down-ink">매도 {share(crowd.sell)}%</span>
      </div>
    </Card>
  )
}

function SignupCard() {
  return (
    <section className="flex flex-col gap-3 rounded-[18px] bg-ink p-4.5 text-white">
      <div className="flex flex-col gap-1">
        <h3 className="text-[17px] font-extrabold">채점 결과를 놓치지 마세요</h3>
        <p className="text-[13px] leading-relaxed text-[#c9cdd6]">
          지금은 게스트예요. 가입하면 이 판정이 그대로 저장되고, 채점일에 알림을 보내드려요.
        </p>
      </div>
      <button type="button" disabled className="min-h-13 rounded-xl bg-[#fee500] text-base font-extrabold text-[#191600] opacity-60">
        카카오로 시작 (준비 중)
      </button>
    </section>
  )
}
