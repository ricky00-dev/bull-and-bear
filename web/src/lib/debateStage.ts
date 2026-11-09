import type { MascotMood } from '../components/Mascot'
import type { Side } from './types'
import type { AcceptedStatement, StreamState } from './useDebateStream'

/** 지금 라운드에서 아직 발언하지 않은 쪽은 생각하는 중. 봉인·중단 뒤에는 쉰다 */
export function sideMood({ phase, currentRound, statements }: Pick<StreamState, 'phase' | 'currentRound' | 'statements'>, side: Side): MascotMood {
  if (phase === 'sealed' || phase === 'failed') return 'done'
  if (phase === 'running' && currentRound && !statements.some((s) => s.side === side && s.round === currentRound)) return 'thinking'
  return 'idle'
}

export function countBySide(statements: AcceptedStatement[]) {
  return {
    bull: statements.filter((s) => s.side === 'bull').length,
    bear: statements.filter((s) => s.side === 'bear').length,
  }
}
