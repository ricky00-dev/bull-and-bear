import type { Decision, JudgmentView, ScoreView } from './types'

/** 판정의 대표 상태: 7일 결과가 있으면 그것, 없으면 3일, 없으면 대기 */
export function headlineScore(j: JudgmentView): ScoreView | undefined {
  return preferredScore(j.scores)
}

/** 응답 배열 순서와 무관하게 가장 긴 채점 기간을 사용한다. */
export function preferredScore(scores: ScoreView[]): ScoreView | undefined {
  return scores.filter(s => s.status === 'SCORED').toSorted((a, b) => b.horizonDays - a.horizonDays)[0]
}

export function correctDecision(excess: number, band: number): Decision {
  return excess > band ? 'BUY' : excess < -band ? 'SELL' : 'HOLD'
}

export function isPending(j: JudgmentView) {
  return j.scores.some((s) => s.status === 'PENDING')
}
