import { useState } from 'react'
import { createPortal } from 'react-dom'
import { describe } from '../lib/glossary'
import { TermText } from './TermText'
import { BottomSheet } from './ui'

/**
 * 중재자 글. "[E1]"은 decisive[0]을 가리키므로 (docs/worker-api.md) 그 자리에 근거 칩을 넣는다.
 * 번호가 없는 예전 글은 그대로 보이고, 목록에 없는 번호는 지운다.
 */
export function VerdictText({ text, decisive }: { text: string; decisive: string[] }) {
  const [open, setOpen] = useState<string | null>(null)
  const info = open ? describe(open) : null
  return (
    <>
      {text.split(/[ \t]*\[E(\d+)\]/).map((part, i) => {
        if (i % 2 === 0) return <TermText key={i} text={part} />
        const id = decisive[Number(part) - 1]
        if (!id) return null
        return (
          <button
            key={i}
            type="button"
            onClick={() => setOpen(id)}
            className="mx-0.5 inline-block rounded-md bg-mod-soft px-1.5 py-0.5 align-baseline text-xs font-bold text-mod active:opacity-70"
          >
            {describe(id).label}
          </button>
        )
      })}
      {info &&
        createPortal(
          <BottomSheet label={`${info.label} 설명`} onClose={() => setOpen(null)}>
            <div className="flex flex-col gap-1">
              <p className="text-[13px] text-sub">중재자가 결정적이라 본 근거</p>
              <p className="text-2xl font-extrabold tracking-tight">{info.label}</p>
            </div>
            {info.desc && <p className="text-[15px] leading-relaxed">{info.desc}</p>}
          </BottomSheet>,
          document.body,
        )}
    </>
  )
}
