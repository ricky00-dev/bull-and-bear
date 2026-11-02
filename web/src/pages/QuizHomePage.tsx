import { useMutation } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router'
import { TabBar } from '../components/TabBar'
import { Card, PrimaryButton, Screen } from '../components/ui'
import { api, ApiError } from '../lib/api'

const STEPS = [
  { title: '이름을 가린 과거 토론', body: '이미 결과가 나온 토론이에요. 종목 이름과 날짜는 정답 공개 때 알려 드려요.' },
  { title: '7거래일 뒤를 맞혀 보세요', body: '코스피보다 2%p 넘게 오르면 매수, 2%p 넘게 내리면 매도, 그 사이면 보류.' },
  { title: '바로 채점, AI와 대결', body: 'AI 중재자도 같은 토론을 보고 판정했어요. 한 판 5문제로 누가 더 맞히는지 겨뤄요.' },
]

/** 타임머신 퀴즈 입구. 전시 현장에서 기다림 없이 바로 결과를 보는 체험. */
export function QuizHomePage() {
  const navigate = useNavigate()
  const start = useMutation({
    mutationFn: api.quizStart,
    onSuccess: (round) => navigate(`/quiz/${round.id}`),
  })
  const error =
    start.error instanceof ApiError
      ? start.error.code === 'QUIZ_EMPTY'
        ? '아직 결과가 나온 토론이 없어요. 토론하고 7거래일이 지나면 문제가 생겨요.'
        : start.error.message
      : start.error
        ? '퀴즈를 시작하지 못했어요. 다시 시도해 주세요.'
        : null

  return (
    <Screen>
      <header className="pt-safe px-5">
        <h1 className="pb-1 pt-5 text-2xl font-extrabold tracking-tight">타임머신 퀴즈</h1>
        <p className="pb-3 text-sm text-sub">결과를 아는 과거로 돌아가 AI와 같은 판정을 내려 보세요</p>
      </header>

      <main className="flex flex-1 flex-col gap-3.5 px-5 pb-6">
        <Card className="flex flex-col gap-4">
          {STEPS.map((s, i) => (
            <div key={s.title} className="flex gap-3">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-ink text-[13px] font-extrabold text-white">
                {i + 1}
              </span>
              <div className="flex flex-col gap-0.5">
                <p className="text-[15px] font-extrabold">{s.title}</p>
                <p className="text-[13px] leading-relaxed text-sub">{s.body}</p>
              </div>
            </div>
          ))}
        </Card>
        <Link to="/quiz/ranking" className="flex items-center justify-between rounded-2xl border border-line bg-white px-4 py-3.5">
          <span className="flex flex-col gap-0.5">
            <span className="text-[15px] font-extrabold">오늘의 랭킹</span>
            <span className="text-xs text-sub">오늘 온 사람들 중 몇 등일까요</span>
          </span>
          <span className="text-[13px] font-bold text-down">보기</span>
        </Link>
        <p className="text-[11px] leading-relaxed text-sub">
          문제는 결과와 상관없이 무작위로 골라요. AI가 맞힌 문제도, 틀린 문제도 섞여 있어요. 퀴즈 기록은 내 판정 통계에 들어가지 않아요. 교육용 모의 퀴즈이며 AI 판정은 투자 권유가 아니에요.
        </p>
        <div className="mt-auto flex flex-col gap-2">
          {error && <p className="text-[13px] font-bold text-up-ink">{error}</p>}
          <PrimaryButton disabled={start.isPending} onClick={() => start.mutate()}>
            {start.isPending ? '문제를 고르는 중…' : '퀴즈 시작'}
          </PrimaryButton>
        </div>
      </main>
      <TabBar />
    </Screen>
  )
}
