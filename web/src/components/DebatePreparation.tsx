import { Link } from 'react-router'
import { preparationStages } from '../lib/experience'
import type { StreamState } from '../lib/debateStreamState'
import { ICONS } from './icons'
import { Icon } from './ui'

export function DebatePreparation({state, onReconnect}: {state:StreamState; onReconnect:()=>void}) {
  if (state.phase === 'sealed') return null
  if (state.phase === 'failed') return <section className="flex flex-col gap-3 rounded-panel bg-surface p-4" role="alert">
    <h2 className="text-base font-bold">토론을 끝까지 준비하지 못했어요</h2><p className="text-sm leading-relaxed text-sub">{state.error} 이미 나온 발언은 읽을 수 있어요. 홈에서 다른 토론을 확인해 보세요.</p><Link to="/" className="pressable flex min-h-touch items-center self-start rounded-control bg-surface-2 px-3 text-sm font-bold">다른 토론 보기</Link>
  </section>
  return <section className="flex flex-col gap-4 rounded-panel bg-surface p-4">
    <div className="flex flex-col gap-1"><h2 className="text-base font-bold">{state.connection === 'failed' ? '토론 연결을 확인해 주세요' : state.connection === 'reconnecting' ? '토론에 다시 연결하고 있어요' : '토론을 준비하고 있어요'}</h2><p className="text-[13px] leading-relaxed text-sub">{state.connection === 'failed' ? '연결 상태를 확인한 뒤 다시 연결해 보세요. 새 토론을 만들지 않고 진행 상황을 다시 불러와요.' : '자료 확인과 발언 생성에 수 분 걸릴 수 있어요. 완료된 단계부터 표시해요.'}</p></div>
    <ol className="flex flex-col gap-3" aria-label="토론 준비 단계">{preparationStages(state).map(step => <li key={step.label} aria-current={step.status === 'current' ? 'step' : undefined} className="flex items-center gap-3 text-sm">
      <span className={`flex size-6 shrink-0 items-center justify-center rounded-full ${step.status === 'done' ? 'bg-point text-on-point' : 'bg-surface-2 text-sub'}`}>{step.status === 'done' ? <Icon d={ICONS.check} size={14} /> : <span aria-hidden="true" className={`size-1.5 rounded-full ${step.status === 'current' ? 'bg-ink' : 'bg-line'}`} />}</span>
      <span className={step.status === 'current' ? 'font-bold' : 'text-sub'}>{step.label}</span><span className="ml-auto text-xs text-sub">{step.status === 'done' ? '완료' : step.status === 'current' ? state.connection === 'open' ? '확인 중' : '연결 대기' : '대기'}</span>
    </li>)}</ol>
    {(state.connection === 'failed' || state.connection === 'reconnecting') && <button type="button" onClick={onReconnect} className="pressable min-h-touch rounded-control bg-surface-2 text-sm font-bold">다시 연결</button>}
    <div className="flex flex-wrap gap-2 border-t border-line-soft pt-3"><Link to="/" className="pressable flex min-h-touch items-center rounded-control bg-surface-2 px-3 text-sm">준비된 다른 토론 보기</Link><Link to="/quiz" className="pressable flex min-h-touch items-center rounded-control bg-surface-2 px-3 text-sm">과거 퀴즈로 연습</Link></div>
    <p className="text-xs leading-relaxed text-sub">홈의 ‘진행 중인 토론’에서 다시 돌아올 수 있어요. AI 판정은 내 판정을 제출한 뒤에만 열려요.</p>
  </section>
}
