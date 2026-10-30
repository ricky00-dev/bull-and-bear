import { useState } from 'react'
import { Screen, TopBar } from '../components/ui'
import { TERMS } from '../lib/glossary'

/** 토론에 나오는 투자 용어 전체. 본문 밑줄과 같은 설명을 한곳에서 찾아본다. */
export function GlossaryPage() {
  const [q, setQ] = useState('')
  const query = q.trim().toLowerCase()
  const items = [...TERMS]
    .sort((a, b) => a.label.localeCompare(b.label, 'ko'))
    .filter((t) => !query || t.label.toLowerCase().includes(query) || t.words.some((w) => w.toLowerCase().includes(query)))

  return (
    <Screen>
      <TopBar title="용어 사전" sub={`${TERMS.length}개`} back="/my" />
      <main className="flex flex-1 flex-col gap-3 px-5 pb-6">
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="용어 찾기 (예: PER, 이동평균)"
          aria-label="용어 찾기"
          className="min-h-12 rounded-xl border border-line bg-white px-4 text-[15px] outline-none focus:border-ink"
        />
        {items.length === 0 ? (
          <p className="py-10 text-center text-sm text-sub">찾는 용어가 없어요</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {items.map((t) => (
              <li key={t.label} className="flex flex-col gap-1 rounded-2xl border border-line bg-white p-4">
                <p className="text-[15px] font-extrabold">{t.label}</p>
                <p className="text-sm leading-relaxed text-sub">{t.desc}</p>
              </li>
            ))}
          </ul>
        )}
      </main>
    </Screen>
  )
}
