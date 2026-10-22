import type { JudgmentView, ScoreView } from './types'

/** 판정의 대표 상태: 7일 결과가 있으면 그것, 없으면 3일, 없으면 대기 */
export function headlineScore(j: JudgmentView): ScoreView | undefined {
  const scored = j.scores.filter((s) => s.status === 'SCORED')
  return scored[scored.length - 1]
}

export function isPending(j: JudgmentView) {
  return j.scores.some((s) => s.status === 'PENDING')
}
