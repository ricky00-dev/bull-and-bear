import type { FeedItem } from './types'

export function groupFeed(items: FeedItem[]) {
  return {
    ready: items.filter(i => i.status === 'COMPLETED'),
    running: items.filter(i => i.status === 'RUNNING'),
  }
}

export type PreparationStage = '자료 고정' | '양측 토론' | 'AI 판정'
/** 표시 단계는 경과 시간이 아닌 실제로 받은 서버 이벤트만 따른다. */
export function preparationStages(state: { asOf: string | null; phase: string }) {
  const stage = state.phase === 'sealed' ? 3 : state.phase === 'moderating' ? 2 : state.asOf ? 1 : 0
  return (['자료 고정', '양측 토론', 'AI 판정'] as PreparationStage[]).map((label, index) => ({
    label, status: index < stage ? 'done' as const : index === stage ? 'current' as const : 'pending' as const,
  }))
}
