import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { IntroSheet } from '../components/IntroSheet'
import { KakaoButton } from '../components/KakaoButton'
import { ICONS } from '../components/icons'
import { TabBar } from '../components/TabBar'
import { Card, ErrorNotice, Icon, Screen, Skeleton } from '../components/ui'
import { api, resetSession } from '../lib/api'
import { TERMS } from '../lib/glossary'

/** 계정 · 퀴즈 누적 기록 · 학습 메뉴. 판정 기록과 적중률은 "내 판정" 탭에 있다. */
export function MyPage() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const quiz = useQuery({ queryKey: ['quiz', 'stats'], queryFn: api.quizStats })
  const [intro, setIntro] = useState(false)

  return (
    <Screen>
      <header className="pt-safe px-5">
        <h1 className="pb-3 pt-5 text-2xl font-extrabold tracking-tight">마이</h1>
      </header>

      <main className="flex flex-1 flex-col gap-3.5 px-5 pb-6">
        {me.data ? (
          <Card className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <span className="flex size-11 items-center justify-center rounded-full bg-surface-2">
                <Icon d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0" size={22} />
              </span>
              <div className="flex flex-col">
                <p className="text-[17px] font-extrabold">{me.data.nickname ?? `게스트 #${me.data.userId.slice(0, 4)}`}</p>
                <p className="text-xs text-sub">{me.data.guest ? '이 기기에만 기록이 남아요' : '카카오 계정'}</p>
              </div>
            </div>
            {me.data.guest ? (
              <>
                <KakaoButton className="text-[15px]" />
                <p className="text-center text-xs text-sub">가입하면 지금까지의 판정·퀴즈 기록이 그대로 이어져요</p>
              </>
            ) : (
              <Logout />
            )}
          </Card>
        ) : me.isError ? (
          <ErrorNotice message="계정 정보를 불러오지 못했어요" onRetry={() => me.refetch()} />
        ) : (
          <Skeleton className="h-36 w-full" />
        )}

        <Card className="flex flex-col gap-2">
          <h2 className="text-sm font-extrabold">타임머신 퀴즈 기록</h2>
          {quiz.isError ? (
            <p className="text-[13px] text-sub">기록을 불러오지 못했어요</p>
          ) : !quiz.data ? (
            <Skeleton className="h-12 w-full" />
          ) : quiz.data.answered === 0 ? (
            <div className="flex items-center justify-between">
              <p className="text-[13px] text-sub">아직 퀴즈를 풀지 않았어요</p>
              <Link to="/quiz" className="text-[13px] font-bold text-point">
                풀어 보기
              </Link>
            </div>
          ) : (
            <div className="flex items-end justify-between">
              <div className="flex items-baseline gap-3">
                <span className="flex flex-col">
                  <span className="text-3xl font-extrabold">{quiz.data.userHits}</span>
                  <span className="text-xs text-sub">나</span>
                </span>
                <span className="text-lg font-bold text-faint">:</span>
                <span className="flex flex-col">
                  <span className="text-3xl font-extrabold text-mod">{quiz.data.aiHits}</span>
                  <span className="text-xs text-mod">AI</span>
                </span>
              </div>
              <p className="text-right text-xs leading-relaxed text-sub">
                {quiz.data.rounds}판 완주
                <br />
                {quiz.data.answered}문제 중 맞힌 개수
              </p>
            </div>
          )}
        </Card>

        <ul className="flex flex-col overflow-hidden rounded-2xl bg-surface">
          <MenuItem to="/quiz/ranking" title="퀴즈 랭킹" sub="닉네임을 정하고 다른 사람과 겨뤄 보기" />
          <MenuItem to="/report" title="AI 성적표" sub="토론 AI와 혼자 판단한 AI, 누가 더 맞혔을까" />
          <MenuItem to="/glossary" title="용어 사전" sub={`PER, 이동평균선 같은 투자 용어 ${TERMS.length}개`} />
          <MenuItem onClick={() => setIntro(true)} title="서비스 소개 다시 보기" sub="불앤베어는 어떻게 하나요" />
        </ul>

        <DeleteMyData />

        <p className="mt-auto pt-4 text-center text-[11px] leading-relaxed text-sub">
          <Link to="/policy/terms" className="underline">
            이용약관
          </Link>
          {' · '}
          <Link to="/policy/privacy" className="font-bold underline">
            개인정보 처리방침
          </Link>
          <br />
          교육용 모의 서비스예요. AI 판정은 투자 권유가 아니에요.
        </p>
      </main>
      <TabBar />
      {intro && <IntroSheet onClose={() => setIntro(false)} />}
    </Screen>
  )
}

/** 이 기기에서만 로그아웃. 기록은 카카오 계정에 남고, 이 기기는 새 게스트로 시작한다 */
function Logout() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return (
    <button
      type="button"
      onClick={() => {
        resetSession()
        queryClient.clear()
        navigate('/', { replace: true })
      }}
      className="min-h-11 self-start text-[13px] text-sub underline"
    >
      이 기기에서 로그아웃
    </button>
  )
}

/** 판정·메모·퀴즈 기록·닉네임을 모두 지우고 새 게스트로 시작한다. 실수로 누르지 않게 한 번 더 묻는다 */
function DeleteMyData() {
  const [asking, setAsking] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const del = useMutation({
    mutationFn: api.deleteMe,
    onSuccess: () => {
      resetSession()
      queryClient.clear()
      navigate('/', { replace: true })
    },
  })
  if (!asking) {
    return (
      <button type="button" onClick={() => setAsking(true)} className="min-h-11 self-center px-3 text-[13px] text-sub underline">
        내 기록 모두 삭제
      </button>
    )
  }
  return (
    <Card className="flex flex-col gap-3 border-up-ink/30">
      <p className="text-[15px] font-extrabold">내 기록을 모두 지울까요?</p>
      <p className="text-[13px] leading-relaxed text-sub">
        판정, 메모, 채점 결과, 퀴즈 기록, 닉네임이 지워지고 되돌릴 수 없어요. 지운 뒤에는 새 게스트로 시작해요.
      </p>
      {del.isError && <p className="text-[13px] font-bold text-up-ink">지우지 못했어요. 잠시 후 다시 시도해 주세요.</p>}
      <div className="grid grid-cols-2 gap-2">
        <button type="button" onClick={() => setAsking(false)} className="min-h-12 rounded-xl bg-surface text-[15px] font-bold">
          취소
        </button>
        <button
          type="button"
          disabled={del.isPending}
          onClick={() => del.mutate()}
          className="min-h-12 rounded-xl bg-up text-[15px] font-bold text-white disabled:opacity-50"
        >
          {del.isPending ? '지우는 중…' : '모두 삭제'}
        </button>
      </div>
    </Card>
  )
}

/** to나 onClick이 없으면 준비 중 항목 (눌리지 않음) */
function MenuItem({ title, sub, to, onClick }: { title: string; sub: string; to?: string; onClick?: () => void }) {
  const body: ReactNode = (
    <>
      <span className="flex flex-col gap-0.5 text-left">
        <span className={`text-[15px] font-bold ${to || onClick ? '' : 'text-faint'}`}>{title}</span>
        <span className="text-xs text-sub">{sub}</span>
      </span>
      {(to || onClick) && <Icon d={ICONS.chevron} size={18} className="shrink-0 text-faint" />}
    </>
  )
  const cls = 'flex min-h-16 w-full items-center justify-between gap-3 px-4 py-3'
  return (
    <li className="border-b border-line-soft last:border-b-0">
      {to ? (
        <Link to={to} className={cls}>
          {body}
        </Link>
      ) : onClick ? (
        <button type="button" onClick={onClick} className={cls}>
          {body}
        </button>
      ) : (
        <div aria-disabled="true" className={cls}>
          {body}
        </div>
      )}
    </li>
  )
}
