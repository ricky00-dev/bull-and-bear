import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { EvidenceSheet } from '../components/EvidenceSheet'
import { ReturnChart } from '../components/ReturnChart'
import { StatementBubble } from '../components/StatementBubble'
import { VerdictText } from '../components/VerdictText'
import { BottomBar, Card, ErrorNotice, PrimaryButton, Screen, Skeleton, TopBar } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { monthDay, pct, pctPoint } from '../lib/format'
import type { Decision, Evidence, QuizAnswer, QuizQuestion, QuizRound } from '../lib/types'
import { DECISION_LABEL } from '../lib/types'

const DECISION_COLOR: Record<Decision, string> = { BUY: 'text-up-ink', HOLD: 'text-ink', SELL: 'text-down-ink' }
const CHOICES: { key: Decision; on: string }[] = [
  { key: 'BUY', on: 'bg-up text-white' },
  { key: 'HOLD', on: 'bg-ink text-white' },
  { key: 'SELL', on: 'bg-down text-white' },
]

/** 문제 → 답 → 공개 → 다음 문제 … → 한 판 결과 */
export function QuizPlayPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const round = useQuery({ queryKey: ['quiz', id], queryFn: () => api.quizRound(id) })
  const [answer, setAnswer] = useState<QuizAnswer | null>(null)

  const submit = useMutation({
    mutationFn: ({ idx, decision }: { idx: number; decision: Decision }) => api.quizAnswer(id, idx, decision),
    onSuccess: (a) => {
      setAnswer(a)
      queryClient.invalidateQueries({ queryKey: ['quiz', id] })
    },
  })

  // 문제·공개가 바뀌면 맨 위부터
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [answer, round.data?.current?.idx])

  const r = round.data
  const sub = r ? `${Math.min((answer?.idx ?? r.current?.idx ?? r.total - 1) + 1, r.total)} / ${r.total}` : undefined

  if (round.isError) {
    return (
      <Screen>
        <TopBar title="타임머신 퀴즈" back="/quiz" />
        <ErrorNotice message="퀴즈를 불러오지 못했어요" onRetry={() => round.refetch()} />
      </Screen>
    )
  }
  if (!r) {
    return (
      <Screen>
        <TopBar title="타임머신 퀴즈" back="/quiz" />
        <div className="flex flex-col gap-3 px-5">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-44 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      </Screen>
    )
  }

  return (
    <Screen>
      <TopBar title="타임머신 퀴즈" sub={sub} back="/quiz" />
      <Progress round={r} />
      {answer ? (
        <AnswerView a={answer} round={r} onNext={() => setAnswer(null)} />
      ) : r.current ? (
        <QuestionView
          q={r.current}
          pending={submit.isPending}
          error={submit.error instanceof ApiError ? submit.error.message : submit.error ? '제출하지 못했어요' : null}
          onAnswer={(decision) => submit.mutate({ idx: r.current!.idx, decision })}
        />
      ) : (
        <Summary round={r} />
      )}
    </Screen>
  )
}

function Progress({ round }: { round: QuizRound }) {
  return (
    <ol className="grid gap-1.5 px-5 pb-3" style={{ gridTemplateColumns: `repeat(${round.total}, 1fr)` }} aria-label="문제 진행">
      {round.questions.map((q) => (
        <li
          key={q.idx}
          className={`h-1.5 rounded-full ${q.decision === null ? 'bg-line' : q.userHit ? 'bg-ok' : 'bg-faint'}`}
          aria-label={`${q.idx + 1}번 ${q.decision === null ? '안 풂' : q.userHit ? '맞힘' : '틀림'}`}
        />
      ))}
    </ol>
  )
}

function QuestionView({
  q,
  pending,
  error,
  onAnswer,
}: {
  q: QuizQuestion
  pending: boolean
  error: string | null
  onAnswer: (d: Decision) => void
}) {
  const [sheet, setSheet] = useState<Evidence | null>(null)
  return (
    <>
      <main className="flex flex-1 flex-col gap-3.5 px-4 pb-4">
        <Card className="flex flex-col gap-1">
          <p className="text-xs font-bold text-mod">정체를 숨긴 종목</p>
          <p className="text-[17px] font-extrabold">
            {q.sector} · {q.period}
          </p>
          <p className="text-xs text-sub">이름은 정답 공개 때 알려 드려요</p>
        </Card>
        <Card className="flex flex-col gap-2">
          <h3 className="text-sm font-extrabold">판정일까지의 주가</h3>
          <ReturnChart chart={q.chart} />
        </Card>
        <h3 className="px-1 pt-1 text-sm font-extrabold">그때 AI들의 토론</h3>
        {q.statements.map((s, i) => (
          <StatementBubble key={i} s={s} onChip={setSheet} />
        ))}
      </main>
      <BottomBar>
        <p className="text-center text-xs text-sub">7거래일 뒤, 코스피보다 ±2%p 넘게 움직였을까요?</p>
        {error && <p className="text-[13px] font-bold text-up-ink">{error}</p>}
        <div className="grid grid-cols-3 gap-2">
          {CHOICES.map((c) => (
            <button
              key={c.key}
              type="button"
              disabled={pending}
              onClick={() => onAnswer(c.key)}
              className={`min-h-14 rounded-2xl text-[17px] font-extrabold disabled:opacity-50 ${c.on}`}
            >
              {DECISION_LABEL[c.key]}
            </button>
          ))}
        </div>
      </BottomBar>
      {sheet && <EvidenceSheet evidence={sheet} onClose={() => setSheet(null)} />}
    </>
  )
}

function AnswerView({ a, round, onNext }: { a: QuizAnswer; round: QuizRound; onNext: () => void }) {
  return (
    <>
      <main className="flex flex-1 flex-col gap-3.5 px-5 pb-4">
        <div className="flex flex-col gap-1">
          <p className="text-[13px] text-sub">
            정답은 <b className={DECISION_COLOR[a.correct]}>{DECISION_LABEL[a.correct]}</b>
          </p>
          <h2 className="text-2xl font-extrabold tracking-tight">{a.userHit ? '맞혔어요!' : '아쉬워요, 빗나갔어요'}</h2>
        </div>

        <Card className="flex flex-col gap-1 border-mod-line bg-mod-soft">
          <p className="text-xs font-bold text-mod">정체 공개</p>
          <p className="text-xl font-extrabold">
            {a.stockName} <span className="text-sm font-bold text-sub">{a.ticker}</span>
          </p>
          <p className="text-xs text-sub">{monthDay(a.baseDate)} 종가 기준 토론</p>
        </Card>

        <div className="grid grid-cols-2 gap-2.5">
          <Verdict who="나" decision={a.decision} hit={a.userHit} />
          <Verdict who="AI 중재자" decision={a.moderatorDecision} hit={a.moderatorHit} mod />
        </div>

        <Card className="flex flex-col gap-3">
          <div className="grid grid-cols-3 gap-2 text-center">
            <Num label="종목" value={pct(a.stockReturn)} />
            <Num label="코스피" value={pct(a.indexReturn)} />
            <Num label="초과수익" value={pctPoint(a.excessReturn)} strong />
          </div>
          <ReturnChart chart={a.chart} />
        </Card>

        <Card className="flex flex-col gap-2">
          <h3 className="text-sm font-extrabold">AI 중재자가 그때 이렇게 봤어요</h3>
          <p className="text-[15px] leading-relaxed">
            <VerdictText text={a.moderatorReasoning} decisive={a.decisiveEvidence} />
          </p>
        </Card>
      </main>
      <BottomBar>
        <PrimaryButton onClick={onNext}>{a.last ? `결과 보기 (나 ${round.userScore} : AI ${round.aiScore})` : '다음 문제'}</PrimaryButton>
      </BottomBar>
    </>
  )
}

function Verdict({ who, decision, hit, mod = false }: { who: string; decision: Decision; hit: boolean; mod?: boolean }) {
  return (
    <Card className={`flex flex-col gap-1 ${mod ? 'border-mod-line' : ''}`}>
      <span className={`text-xs ${mod ? 'text-mod' : 'text-sub'}`}>{who}</span>
      <span className={`text-[22px] font-extrabold ${DECISION_COLOR[decision]}`}>{DECISION_LABEL[decision]}</span>
      <span className={`text-[13px] font-bold ${hit ? 'text-ok' : 'text-sub'}`}>{hit ? '적중' : '빗나감'}</span>
    </Card>
  )
}

function Num({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-sub">{label}</span>
      <span className={`text-lg ${strong ? 'font-extrabold' : 'font-bold'}`}>{value}</span>
    </div>
  )
}

function Summary({ round }: { round: QuizRound }) {
  const navigate = useNavigate()
  const again = useMutation({ mutationFn: api.quizStart, onSuccess: (r) => navigate(`/quiz/${r.id}`, { replace: true }) })
  const { userScore: me, aiScore: ai, total } = round
  const headline = me > ai ? 'AI를 이겼어요!' : me === ai ? 'AI와 비겼어요' : '이번엔 AI가 이겼어요'

  return (
    <>
      <main className="flex flex-1 flex-col gap-3.5 px-5 pb-4">
        <Card className="flex flex-col items-center gap-3 py-6 text-center">
          <p className="text-[13px] font-bold text-mod">한 판 결과</p>
          <h2 className="text-2xl font-extrabold tracking-tight">{headline}</h2>
          <div className="flex items-baseline gap-4">
            <span className="flex flex-col">
              <span className="text-4xl font-extrabold">{me}</span>
              <span className="text-xs text-sub">나</span>
            </span>
            <span className="text-xl font-bold text-faint">:</span>
            <span className="flex flex-col">
              <span className="text-4xl font-extrabold text-mod">{ai}</span>
              <span className="text-xs text-mod">AI</span>
            </span>
          </div>
          <p className="text-xs text-sub">{total}문제 중 맞힌 개수</p>
        </Card>
        <p className="text-[13px] leading-relaxed text-sub">
          단기 주가는 전문가도 맞히기 어려워요. 결과보다 어떤 근거가 실제로 맞았는지 돌아보는 게 진짜 연습이에요.
        </p>
        <Link to="/quiz/ranking" className="text-center text-sm font-bold text-down underline-offset-2 hover:underline">
          오늘의 랭킹에서 내 순위 보기
        </Link>
        <Link to="/" className="text-center text-sm font-bold text-down underline-offset-2 hover:underline">
          오늘 토론을 실제로 판정해 보기
        </Link>
        <p className="text-center text-[11px] leading-relaxed text-sub">교육용 모의 퀴즈예요. AI 판정은 투자 권유가 아니에요.</p>
      </main>
      <BottomBar>
        <PrimaryButton disabled={again.isPending} onClick={() => again.mutate()}>
          {again.isPending ? '문제를 고르는 중…' : '한 판 더'}
        </PrimaryButton>
      </BottomBar>
    </>
  )
}
