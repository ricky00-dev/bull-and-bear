import { useEffect, useReducer, useState } from 'react'
import { debateStreamUrl } from './api'
import { initialStreamState, reduceDebateStream, type StreamState } from './debateStreamState'
export type { AcceptedStatement, StreamState } from './debateStreamState'

const EVENT_TYPES = [
  'snapshot_created', 'turn_started', 'tool_call', 'statement_rejected', 'statement_accepted',
  'extra_round_requested', 'moderator_started', 'debate_sealed', 'debate_failed',
]

/**
 * 토론 SSE 구독. 끝난 토론이면 서버가 처음부터 재생하고 닫는다.
 * 끊기면 EventSource가 Last-Event-ID로 알아서 이어 받는다.
 */
export function useDebateStream(debateId: string | undefined): StreamState & { reconnect: () => void } {
  const [state, dispatch] = useReducer(reduceDebateStream, initialStreamState)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    dispatch({type:'reset'})
    if (!debateId) return
    let source: EventSource | null = null
    let cancelled = false

    debateStreamUrl(debateId).then((url) => {
      if (cancelled) return
      source = new EventSource(url)
      source.onopen = () => { if (!cancelled) dispatch({ type: 'open' }) }
      source.onerror = () => {
        if (cancelled) return
        if (source?.readyState === EventSource.CONNECTING) dispatch({ type: 'lost' })
        else dispatch({type:'connect_failed'})
      }
      for (const type of EVENT_TYPES) {
        source.addEventListener(type, (e) => {
          if (cancelled) return
          const ev = e as MessageEvent<string>
          dispatch({ seq: Number(ev.lastEventId), type, data: JSON.parse(ev.data || '{}') })
          if (type === 'debate_sealed' || type === 'debate_failed') source?.close()
        })
      }
    }).catch(() => { if (!cancelled) dispatch({type:'connect_failed'}) })

    return () => {
      cancelled = true
      source?.close()
    }
  }, [debateId, attempt])

  return {...state, reconnect: () => setAttempt(n => n+1)}
}
