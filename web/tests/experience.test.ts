import { test } from 'node:test'
import assert from 'node:assert/strict'
import { groupFeed, preparationStages } from '../src/lib/experience.ts'
import { decodeJudgmentDraft } from '../src/lib/judgmentDraft.ts'
import { initialStreamState, reduceDebateStream } from '../src/lib/debateStreamState.ts'
import type { FeedItem } from '../src/lib/types.ts'
const item = (status: FeedItem['status'], id:string):FeedItem=>({debateId:id,status,ticker:'005930',stockName:'삼성전자',scheduled:false,dataDate:'2026-10-22',createdAt:'2026-10-22T00:00:00Z',judged:0,mine:false})
test('완료된 토론만 바로 읽기, 진행 중·실패는 섞지 않는다',()=>{
 const g=groupFeed([item('RUNNING','r'),item('FAILED','f'),item('COMPLETED','c')])
 assert.deepEqual(g.ready.map(i=>i.debateId),['c']);assert.deepEqual(g.running.map(i=>i.debateId),['r'])
 assert.deepEqual(groupFeed([]),{ready:[],running:[]})
})
test('자료 고정은 snapshot 이벤트 전까지 완료로 표시하지 않는다',()=>{
 assert.deepEqual(preparationStages({phase:'running',asOf:null}).map(s=>s.status),['current','pending','pending'])
 assert.deepEqual(preparationStages({phase:'running',asOf:'2026-10-22'}).map(s=>s.status),['done','current','pending'])
 assert.deepEqual(preparationStages({phase:'moderating',asOf:'2026-10-22'}).map(s=>s.status),['done','done','current'])
 assert.ok(preparationStages({phase:'sealed',asOf:'2026-10-22'}).every(s=>s.status==='done'))
})
test('임시 판정·확신·여러 줄 한글 메모를 그대로 복원한다',()=>{
 const draft={decision:'SELL',confidence:90,memo:'첫 줄 근거\n두 번째 생각'}
 assert.deepEqual(decodeJudgmentDraft(JSON.stringify(draft)),draft)
})
test('손상된 초안과 범위 밖 확신·긴 메모를 안전하게 읽는다',()=>{
 for(const raw of [null,'{bad','[]','null'])assert.deepEqual(decodeJudgmentDraft(raw),{decision:null,confidence:70,memo:''})
 assert.deepEqual(decodeJudgmentDraft('{"decision":"UNKNOWN","confidence":900,"memo":5}'),{decision:null,confidence:100,memo:''})
 assert.equal(decodeJudgmentDraft(JSON.stringify({memo:'가'.repeat(210),confidence:53})).memo.length,200)
 assert.equal(decodeJudgmentDraft('{"confidence":-5}').confidence,50)
})
test('연결 재시도와 토론 자체 실패를 구분하고 연결 끊김에도 발언은 보존한다',()=>{
 const state=reduceDebateStream(initialStreamState,{seq:2,type:'statement_accepted',data:{side:'bull',round:'opening',attempts:1,statement:{claim:'주장',argument:'',evidence:[]}}})
 const lost=reduceDebateStream(state,{type:'lost'})
 assert.equal(lost.statements.length,1);assert.equal(lost.lastSeq,2);assert.equal(lost.connection,'reconnecting')
 const failed=reduceDebateStream(state,{type:'connect_failed'})
 assert.notEqual(failed.phase,'failed');assert.equal(failed.connection,'failed')
 const stopped=reduceDebateStream(state,{seq:3,type:'debate_failed',data:{error:{message:'중단'}}})
 assert.equal(stopped.phase,'failed');assert.equal(stopped.error,'중단')
})
test('다른 토론·수동 재연결은 상태를 초기화하고 같은 seq 재전송은 중복하지 않는다',()=>{
 const first=reduceDebateStream(initialStreamState,{seq:2,type:'snapshot_created',data:{as_of:'2026-10-22'}})
 assert.equal(reduceDebateStream(first,{seq:2,type:'snapshot_created',data:{as_of:'2099-01-01'}}),first)
 const reset=reduceDebateStream(first,{type:'reset'})
 assert.equal(reset.lastSeq,0);assert.equal(reset.asOf,null);assert.equal(reset.phase,'connecting')
 assert.equal(reduceDebateStream(reset,{type:'open'}).connection,'open')
})
