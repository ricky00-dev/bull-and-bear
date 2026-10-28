import { type ReactNode, useEffect } from 'react'
import { useNavigate } from 'react-router'

/** 모바일 우선: 폰 폭 기준, 넓은 화면에서는 가운데 480px */
export function Screen({ children }: { children: ReactNode }) {
  return <div className="mx-auto flex min-h-full w-full max-w-[480px] flex-col bg-ground">{children}</div>
}

export function TopBar({ title, sub, back }: { title: string; sub?: string; back?: string }) {
  const navigate = useNavigate()
  return (
    <header className="pt-safe sticky top-0 z-10 bg-ground">
      <div className="flex items-center gap-1 px-3 pb-2.5 pt-3.5">
        <button
          type="button"
          aria-label="뒤로"
          onClick={() => (back ? navigate(back) : navigate(-1))}
          className="flex size-11 items-center justify-center rounded-xl"
        >
          <Icon d="M15 6l-6 6 6 6" size={22} />
        </button>
        <div className="flex min-w-0 flex-col">
          <h1 className="truncate text-base font-extrabold tracking-tight">{title}</h1>
          {sub && <p className="text-[11px] text-sub">{sub}</p>}
        </div>
      </div>
    </header>
  )
}

/** 화면 아래 고정 행동 영역. 홈 바 영역은 비운다. */
export function BottomBar({ children }: { children: ReactNode }) {
  return (
    <div className="pb-safe sticky bottom-0 z-10 flex flex-col gap-2 border-t border-line bg-white px-5 pt-3">
      {children}
    </div>
  )
}

export function PrimaryButton({
  children,
  disabled,
  onClick,
  variant = 'solid',
}: {
  children: ReactNode
  disabled?: boolean
  onClick?: () => void
  variant?: 'solid' | 'outline'
}) {
  const base = 'min-h-14 w-full rounded-2xl text-[17px] font-extrabold transition-colors'
  const style = disabled
    ? 'bg-line text-sub'
    : variant === 'solid'
      ? 'bg-ink text-white active:bg-black'
      : 'border-[1.5px] border-ink bg-white text-ink'
  return (
    <button type="button" disabled={disabled} onClick={onClick} className={`${base} ${style}`}>
      {children}
    </button>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-line bg-white p-4 ${className}`}>{children}</section>
}

export function Icon({ d, size = 20, stroke = 2, className = '' }: { d: string; size?: number; stroke?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      <path d={d} />
    </svg>
  )
}

/** 데이터를 기다리는 동안의 회색 막대 */
export function Skeleton({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-lg bg-line ${className}`} />
}

export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <p className="text-[15px] font-bold">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="min-h-11 rounded-xl border border-line bg-white px-4 text-sm">
          다시 시도
        </button>
      )}
    </div>
  )
}

/** 아래에서 올라오는 시트. 배경을 누르거나 Esc로 닫는다. */
export function BottomSheet({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-30 flex flex-col justify-end">
      <button type="button" aria-label="닫기" onClick={onClose} className="absolute inset-0 bg-ink/45" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="pb-safe animate-rise relative mx-auto flex w-full max-w-[480px] flex-col gap-3.5 rounded-t-[22px] bg-white px-5.5 pt-2.5"
      >
        <div className="h-1 w-10 self-center rounded-full bg-line" />
        {children}
        <PrimaryButton onClick={onClose}>확인</PrimaryButton>
      </div>
    </div>
  )
}
