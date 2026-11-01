// Run against a local Vite server. All API calls are intercepted; no models/market services.
// PLAYWRIGHT_MODULE may point to an installed Playwright index.mjs (file URL).
import assert from 'node:assert/strict'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright')
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH })
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' })
  const calls = []
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  let fail = false
  let empty = false
  let ready = true
  const common = { snapshot_id: 'saved', context_id: 'ctx', ticker: '005930', snapshot_as_of: '2026-10-30', reasons: [] }
  await page.addInitScript(() => localStorage.setItem('bb.token', 'test-guest'))
  await page.route('**/api/**', async route => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    const json = value => route.fulfill({ json: value, headers: { 'Access-Control-Allow-Origin': '*' } })
    if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: {
      'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*',
    } })
    if (path.endsWith('/stream')) return route.fulfill({ contentType: 'text/event-stream', body: 'id: 1\nevent: debate_failed\ndata: {"error":{"message":"테스트용 저장 토론"}}\n\n', headers: { 'Access-Control-Allow-Origin': '*' } })
    if (path.endsWith('/rag/search') || path.endsWith('/rag/facts')) {
      calls.push({ path, body: req.postDataJSON() })
      assert.equal(req.headers().authorization, 'Bearer test-guest')
      if (fail) return route.fulfill({ status: 503, json: { error: { code: 'WORKER_UNAVAILABLE', message: '자료 조회를 완료하지 못했습니다.' } }, headers: { 'Access-Control-Allow-Origin': '*' } })
      if (path.endsWith('/search')) return json({ ...common, mode: 'documents', answerability: empty ? 'no_documents' : 'documents_found', answer_scope: 'retrieved_documents_not_verified_numeric_answer', documents: empty ? [] : [{ chunk_id: 'per', text: 'PER은 주가수익비율입니다.', applicability: '개념 설명', limitations: ['수익 예측 아님'], horizons: ['common'] }] })
      return json({ ...common, mode: 'facts', answerability: empty ? 'insufficient_evidence' : 'supported_fact', reasons: empty ? ['fact_date_mismatch'] : [], facts: empty ? [] : [{ fact_id: 'VAL.PER_TTM', ticker: '005930', value: 12.3, unit: 'x', as_of: '2026-10-30', source: 'derived', inputs: [], verified_lineage: ['VAL.PER_TTM'] }] })
    }
    if (path === '/api/debates/saved-debate') return json({ id: 'saved-debate', stockName: '삼성전자', ticker: '005930', status: 'FAILED', snapshotId: ready ? 'saved' : null, tradeDate: ready ? '2026-10-30' : null, createdAt: '2026-10-30T08:00:00Z' })
    throw new Error(`Unexpected API call: ${req.method()} ${path}`)
  })
  const url = `${process.env.WEB_TEST_URL ?? 'http://127.0.0.1:5173'}/debates/saved-debate`
  await page.goto(url)
  await page.getByText('자료 찾아보기', { exact: true }).click()
  await page.getByLabel('찾을 내용').fill('PER 뜻과 현재 값')
  assert.equal(calls.length, 0)
  await page.getByRole('button', { name: '문서 검색하기' }).click()
  await page.getByText('PER은 주가수익비율입니다.').waitFor()
  assert.deepEqual(calls.at(-1).body, { question: 'PER 뜻과 현재 값' })
  await page.getByLabel('수치 조회', { exact: true }).check()
  assert.equal(await page.getByText('PER은 주가수익비율입니다.').count(), 0)
  await page.getByRole('combobox').selectOption('per_ttm')
  await page.getByLabel('기준일 (선택)').fill('2026-10-30')
  await page.getByRole('button', { name: '수치 조회하기' }).click()
  await page.getByText('12.3 x', { exact: true }).waitFor()
  assert.deepEqual(calls.at(-1).body, { metric: 'per_ttm', asOf: '2026-10-30', unit: 'x' })
  empty = true
  await page.getByRole('button', { name: '수치 조회하기' }).click()
  await page.getByText('요청한 날짜와 저장된 수치의 기준일이 다릅니다.').waitFor()
  assert.equal(await page.getByText('12.3 x', { exact: true }).count(), 0)
  await page.getByLabel('문서 검색', { exact: true }).check()
  await page.getByRole('button', { name: '문서 검색하기' }).click()
  await page.getByText('조건에 맞는 문서가 없습니다. 검색어를 바꿔 보세요.').waitFor()
  fail = true
  await page.getByRole('button', { name: '문서 검색하기' }).click()
  await page.getByRole('alert').waitFor()
  assert.equal(await page.getByText('조건에 맞는 문서가 없습니다. 검색어를 바꿔 보세요.').count(), 0)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  ready = false
  await page.reload()
  await page.getByText('자료 찾아보기', { exact: true }).click()
  assert.equal(await page.getByRole('button', { name: '문서 검색하기' }).isDisabled(), true)
  assert.equal(calls.length, 5)
  assert.deepEqual(errors, [])
  console.log('RAG browser smoke passed: explicit modes/payloads, stale-result clearing, missing evidence, empty docs, error, unready snapshot, mobile overflow; 5 read-only queries.')
} finally { await browser.close() }
