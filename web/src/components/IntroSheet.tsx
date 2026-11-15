import { useState } from 'react'
import { useNavigate } from 'react-router'
import { ModalSheet, PrimaryButton } from './ui'

const KEY = 'bb.intro.v1'

function seen(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

const STEPS = [
  ['AI 두 명이 토론해요', '매수 AI와 매도 AI가 실제 시세·재무·공시·뉴스를 근거로 맞서요. 근거를 눌러 원자료를 확인할 수 있어요.'],
  ['내가 먼저 판정해요', '토론을 보고 매수·보류·매도 중 하나를 골라요. 이때까지 AI 심판의 판정은 가려져 있어요.'],
  ['실제 주가로 채점해요', '판정을 내면 AI 판정이 공개되고, 3·7거래일 뒤 실제 주가로 나와 AI를 함께 채점해요.'],
] as const

/** 첫 방문 안내 + 투자 유의 고지. 한 번 확인하면 다시 뜨지 않는다. onClose를 주면 마이 탭처럼 언제든 다시 연다. */
export function IntroSheet({ onClose }: { onClose?: () => void }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(() => !!onClose || !seen())
  if (!open) return null

  const close = () => {
    onClose?.()
    try {
      localStorage.setItem(KEY, '1')
    } catch {
      // 저장 못 하면 다음 방문에 다시 보여 준다
    }
    setOpen(false)
  }

  return (
    <ModalSheet label="불앤베어는 이렇게 해요" onClose={close}>
        <h2 id="intro-title" className="text-xl font-extrabold tracking-tight">
          불앤베어는 이렇게 해요
        </h2>
        <ol className="flex flex-col gap-3.5">
          {STEPS.map(([title, desc], i) => (
            <li key={title} className="flex gap-3">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-surface-2 text-xs font-extrabold text-ink">
                {i + 1}
              </span>
              <span className="flex flex-col gap-0.5">
                <span className="text-[15px] font-bold">{title}</span>
                <span className="text-[13px] leading-relaxed text-sub">{desc}</span>
              </span>
            </li>
          ))}
        </ol>
        <p className="rounded-xl bg-surface-2 px-3.5 py-3 text-xs leading-relaxed text-sub">
          <b className="text-ink">교육용 모의 서비스예요.</b> AI 토론·판정과 채점 결과는 투자 권유나 종목 추천이 아니에요.
          실제 투자 판단과 그 결과의 책임은 본인에게 있어요.
        </p>
        <div className="pb-4">
          <PrimaryButton onClick={close}>{onClose ? '확인했어요' : '토론부터 살펴보기'}</PrimaryButton>
          {!onClose && <button type="button" onClick={() => {close();navigate('/quiz')}} className="pressable mt-2 min-h-touch w-full rounded-control bg-surface-2 text-sm font-bold">과거 퀴즈로 먼저 연습하기</button>}
        </div>
    </ModalSheet>
  )
}
