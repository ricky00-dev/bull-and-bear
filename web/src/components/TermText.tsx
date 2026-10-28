import { useState } from 'react'
import { createPortal } from 'react-dom'
import { splitTerms, type Term } from '../lib/glossary'
import { BottomSheet } from './ui'

/** 본문 속 투자 용어에 점선 밑줄을 긋고, 누르면 쉬운 설명을 띄운다. 시트는 <p> 안에 둘 수 없어 body로 보낸다. */
export function TermText({ text }: { text: string }) {
  const [open, setOpen] = useState<Term | null>(null)
  return (
    <>
      {splitTerms(text).map((p, i) =>
        typeof p === 'string' ? (
          p
        ) : (
          <button
            key={i}
            type="button"
            onClick={() => setOpen(p.term)}
            className="underline decoration-faint decoration-dotted decoration-[1.5px] underline-offset-4 active:bg-line-soft"
          >
            {p.text}
          </button>
        ),
      )}
      {open &&
        createPortal(
          <BottomSheet label={`${open.label} 설명`} onClose={() => setOpen(null)}>
            <div className="flex flex-col gap-1">
              <p className="text-[13px] text-sub">용어 풀이</p>
              <p className="text-2xl font-extrabold tracking-tight">{open.label}</p>
            </div>
            <p className="text-[15px] leading-relaxed">{open.desc}</p>
          </BottomSheet>,
          document.body,
        )}
    </>
  )
}
