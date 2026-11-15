import { type ReactNode, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router'
import logoMark from '../assets/logo-mark.png'

/** 상세 흐름은 읽기 폭을 유지하고, 홈은 넓은 화면에서 두 열을 사용한다. */
export function Screen({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return <div className={`mx-auto flex min-h-dvh w-full flex-col bg-ground ${wide ? 'max-w-[480px] md:max-w-[720px] lg:max-w-[960px]' : 'max-w-[480px] md:max-w-[720px] lg:max-w-[880px]'}`}>{children}</div>
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
          className="pressable flex size-touch items-center justify-center rounded-control transition-colors"
        >
          <Icon d="M15 6l-6 6 6 6" size={22} />
        </button>
        <div className="flex min-w-0 flex-col">
          <h1 className="truncate text-base font-extrabold tracking-tight">{title}</h1>
          {sub && <p className="text-xs leading-relaxed text-sub">{sub}</p>}
        </div>
      </div>
    </header>
  )
}

/** 화면 아래 고정 행동 영역. 홈 바 영역은 비운다. */
export function BottomBar({ children }: { children: ReactNode }) {
  return (
    <div className="action-bar pb-safe sticky bottom-0 z-10 flex flex-col gap-2 glass-bar px-5 pt-3">
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
  const base = 'min-h-14 w-full rounded-control px-4 text-base font-bold transition-[background-color,transform] duration-150 motion-safe:enabled:active:scale-[0.96]'
  const style = disabled
    ? 'bg-line text-sub'
    : variant === 'solid'
      ? 'bg-point text-on-point hover:brightness-110 active:brightness-95'
      : 'pressable bg-surface-2 text-ink'
  return (
    <button type="button" disabled={disabled} onClick={onClick} className={`${base} ${style}`}>
      {children}
    </button>
  )
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-panel bg-surface p-4 ${className}`}>{children}</section>
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
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <p className="text-[15px] font-bold">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="min-h-11 rounded-xl bg-surface px-4 text-sm">
          다시 시도
        </button>
      )}
    </div>
  )
}

/** 네이티브 dialog가 포커스 가두기·배경 비활성화·포커스 복귀를 담당한다. */
export function ModalSheet({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current!
    const previous = document.activeElement
    const overflow = document.body.style.overflow
    dialog.showModal()
    dialog.querySelector<HTMLElement>('[data-sheet-content]')?.focus({ preventScroll: true })
    const viewport = window.visualViewport
    const fitViewport = () => {
      if (!viewport) return
      dialog.style.height = `${viewport.height}px`
      dialog.style.top = `${viewport.offsetTop}px`
      const content = dialog.querySelector<HTMLElement>('[data-sheet-content]')
      if (content) content.style.maxHeight = `${Math.min(window.innerHeight*0.9, viewport.height-16)}px`
    }
    fitViewport()
    viewport?.addEventListener('resize', fitViewport)
    viewport?.addEventListener('scroll', fitViewport)
    document.body.style.overflow = 'hidden'
    return () => {
      dialog.close()
      viewport?.removeEventListener('resize', fitViewport)
      viewport?.removeEventListener('scroll', fitViewport)
      document.body.style.overflow = overflow
      if (previous instanceof HTMLElement) previous.focus({ preventScroll: true })
    }
  }, [])

  return (
    <dialog
      ref={ref}
      aria-label={label}
      className="modal-sheet fixed inset-0 m-0 h-full max-h-none w-full max-w-none border-0 bg-transparent p-0 text-ink"
      onCancel={(event) => { event.preventDefault(); onClose() }}
      onKeyDown={(event) => {
        if (event.key !== 'Tab') return
        const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])')].filter((el) => el.getClientRects().length > 0)
        const first = controls[0]
        const last = controls.at(-1)
        if (!first || !last) { event.preventDefault(); return }
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }}
    >
      <div className="flex min-h-full flex-col justify-end md:justify-center md:p-6" onClick={(event) => { if (event.target === event.currentTarget) onClose() }}>
        <div
          data-sheet-content
          tabIndex={-1}
          className="sheet-content pb-safe animate-rise relative mx-auto flex max-h-full w-full max-w-[480px] flex-col gap-4 overflow-y-auto rounded-t-sheet md:rounded-sheet bg-surface px-5 pt-3 focus:outline-none"
        >
          <div className="sticky top-0 z-10 flex min-h-touch shrink-0 items-center justify-center bg-surface"><div aria-hidden="true" className="h-1 w-10 rounded-full bg-line" /><button type="button" onClick={onClose} aria-label="창 닫기" className="pressable absolute right-0 flex size-touch items-center justify-center rounded-control text-sub"><Icon d="M6 6l12 12M6 18L18 6" size={20} /></button></div>
          {children}
        </div>
      </div>
    </dialog>
  )
}

/** 아래에서 올라오는 시트. 배경을 누르거나 Esc로 닫는다. */
export function BottomSheet({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  return (
    <ModalSheet label={label} onClose={onClose}>
      {children}
      <PrimaryButton onClick={onClose}>확인</PrimaryButton>
    </ModalSheet>
  )
}

/** 불앤베어 로고: 앱 아이콘과 같은 그림(이마를 맞댄 황소와 곰). 홈 머리·왼쪽 메뉴·전시 화면이 같이 쓴다 */
export function Logo() {
  return (
    <span className="flex items-center gap-2">
      <img src={logoMark} alt="" width={28} height={28} className="size-7 rounded-[7px]" />
      <span className="text-lg font-extrabold tracking-tight">불앤베어</span>
    </span>
  )
}
