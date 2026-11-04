import { useState } from 'react'
import { decodeEvidencePicks, EVIDENCE_DRAFT_PREFIX, toggleEvidencePick } from './evidence'

const key = (id: string) => `${EVIDENCE_DRAFT_PREFIX}${id}`
function read(id: string) {
  try { return decodeEvidencePicks(sessionStorage.getItem(key(id))) } catch { return [] }
}

/** 같은 탭의 토론→판정 이동·새로고침에서만 보관한다. 제출 전에는 서버로 보내지 않는다. */
export function useEvidencePicks(debateId: string) {
  const [state, setState] = useState(() => ({ id: debateId, picks: read(debateId) }))
  const picks = state.id === debateId ? state.picks : read(debateId)
  const toggle = (sourceId: string) => {
    const next = toggleEvidencePick(picks, sourceId)
    setState({ id: debateId, picks: next })
    try { sessionStorage.setItem(key(debateId), JSON.stringify(next)) } catch { /* 이번 화면에서는 선택 유지 */ }
  }
  const clear = () => {
    setState({ id: debateId, picks: [] })
    try { sessionStorage.removeItem(key(debateId)) } catch { /* 선택 UI는 초기화 */ }
  }
  return { picks, toggle, clear }
}
