import { test } from 'node:test'
import assert from 'node:assert/strict'
import { decodeEvidencePicks, pairStatements, previousOpponent, toggleEvidencePick, type DebateTurn } from '../src/lib/evidence.ts'
import { correctDecision, preferredScore } from '../src/lib/score.ts'
import type { Round, ScoreView, Side } from '../src/lib/types.ts'
const turn = (seq: number, side: Side, round: Round): DebateTurn => ({ seq, side, round, attempts: 1, statement: { claim: `${seq}`, argument: '', evidence: [] } })
test('같은 라운드로 비교하고 아직 오지 않은 상대 발언은 만들지 않는다', () => {
  const pairs = pairStatements([turn(9, 'bull', 'rebuttal'), turn(4, 'bear', 'opening'), turn(2, 'bull', 'opening')])
  assert.deepEqual(pairs.map(p => [p.round, p.bull?.seq, p.bear?.seq]), [['opening', 2, 4], ['rebuttal', 9, undefined]])
})
test('여러 추가 질문의 발언을 빠짐없이 순서대로 표시한다', () => {
  const pairs = pairStatements([turn(16, 'bear', 'extra'), turn(11, 'bull', 'extra'), turn(18, 'bull', 'extra'), turn(20, 'bear', 'extra')])
  assert.deepEqual(pairs.map(p => [p.bull?.seq, p.bear?.seq]), [[11, 16], [18, 20]])
  assert.equal(new Set(pairs.map(p => p.key)).size, 2)
})
test('앞선 상대 주장 링크는 다른 라운드의 이전 발언만 가리킨다', () => {
  const all = [turn(2,'bull','opening'), turn(4,'bear','opening'), turn(9,'bull','rebuttal'), turn(11,'bear','rebuttal')]
  assert.equal(previousOpponent(all[3], all)?.seq, 2)
  assert.equal(previousOpponent(all[0], all), undefined)
})
test('담은 두 근거를 세 번째 선택으로 조용히 교체하지 않는다', () => {
  const two = ['PX.CLOSE', 'VAL.PBR']
  assert.deepEqual(toggleEvidencePick(two, 'VAL.ROE_TTM'), two)
  assert.deepEqual(toggleEvidencePick(two, 'PX.CLOSE'), ['VAL.PBR'])
  assert.deepEqual(toggleEvidencePick(['VAL.PBR'], 'PX.CLOSE'), ['VAL.PBR','PX.CLOSE'])
})
test('손상된 초안·비배열·중복·잘못된 항목은 복구하고 최대 두 개만 읽는다', () => {
  for (const value of [null, '{bad', '{}', 'null']) assert.deepEqual(decodeEvidencePicks(value), [])
  assert.deepEqual(decodeEvidencePicks('[null,5,"","PX.CLOSE","PX.CLOSE","VAL.PBR","VAL.ROE_TTM"]'), ['PX.CLOSE','VAL.PBR'])
})
test('보류 경계 ±2%p는 보류이고 경계 밖만 매수·매도다', () => {
  assert.equal(correctDecision(2,2), 'HOLD')
  assert.equal(correctDecision(-2,2), 'HOLD')
  assert.equal(correctDecision(2.00001,2), 'BUY')
  assert.equal(correctDecision(-2.00001,2), 'SELL')
})
const score = (days: number, status: 'PENDING' | 'SCORED'): ScoreView => ({ horizonDays: days, status, scheduledDate: '2026-11-10', scoredTradeDate: status === 'SCORED' ? '2026-11-10' : null, stockReturn:null,indexReturn:null,excessReturn:null,userHit:null,moderatorHit:null })
test('배열 순서와 무관하게 7일 최종 결과 우선, 없으면 3일 중간 결과', () => {
  assert.equal(preferredScore([score(7,'SCORED'),score(3,'SCORED')])?.horizonDays,7)
  assert.equal(preferredScore([score(7,'PENDING'),score(3,'SCORED')])?.horizonDays,3)
  assert.equal(preferredScore([score(7,'PENDING'),score(3,'PENDING')]),undefined)
})
