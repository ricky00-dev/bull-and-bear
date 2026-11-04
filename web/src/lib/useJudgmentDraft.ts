import { useState } from 'react'
import { decodeJudgmentDraft, EMPTY_JUDGMENT_DRAFT, JUDGMENT_DRAFT_PREFIX, type JudgmentDraft } from './judgmentDraft'
function load(id: string) {
  try { return {draft:decodeJudgmentDraft(sessionStorage.getItem(JUDGMENT_DRAFT_PREFIX+id)), saved:true} } catch { return {draft:{...EMPTY_JUDGMENT_DRAFT},saved:false} }
}
export function useJudgmentDraft(id: string) {
  const [state,setState] = useState(() => ({id,...load(id)}))
  const current = state.id === id ? state : load(id)
  function update(change: Partial<JudgmentDraft>) {
    const draft = {...current.draft,...change}
    let saved = true
    try { sessionStorage.setItem(JUDGMENT_DRAFT_PREFIX+id, JSON.stringify(draft)) } catch { saved = false }
    setState({id,draft,saved})
  }
  function clear() {
    try {sessionStorage.removeItem(JUDGMENT_DRAFT_PREFIX+id)} catch { /* 화면 상태는 초기화 */ }
    setState({id,draft:{...EMPTY_JUDGMENT_DRAFT},saved:true})
  }
  return {...current, update, clear, hasDraft:current.draft.decision !== null || current.draft.memo !== '' || current.draft.confidence !== 70}
}
