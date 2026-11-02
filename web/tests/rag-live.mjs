// Actual browser -> Spring -> Python -> saved storage; no API response stubs.
// External assets (Google Fonts) are blocked; local requests pass through unchanged.
// Requires a prepared isolated RAG_E2E_MANIFEST and running services. See evaluation report.
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const manifest = JSON.parse(await fs.readFile(process.env.RAG_E2E_MANIFEST, 'utf8'))
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright')
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH })
const api = process.env.RAG_E2E_API ?? 'http://127.0.0.1:18080'
const web = process.env.WEB_TEST_URL ?? 'http://127.0.0.1:15173'
const report = { schema: 'rag-live-e2e-v1', response_stubs: false, source_sha256: manifest.source_sha256, checks: [], results: {} }
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' })
  const errors = []
  const remote = []
  const posts = []
  await page.route('**/*', route => {
    const host = new URL(route.request().url()).hostname
    return ['127.0.0.1', 'localhost'].includes(host) ? route.continue() : route.abort()
  })
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => {
    const url = new URL(request.url())
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) remote.push(url.origin)
    if (request.method() === 'POST') posts.push(url.pathname)
  })
  await page.goto(`${web}/debates/${manifest.real_debate}`)
  await page.getByText('자료 찾아보기', { exact: true }).click()
  await page.getByLabel('수치 조회', { exact: true }).check()
  const submit = async (route, text) => {
    const response = page.waitForResponse(r => r.url().endsWith(`/rag/${route}`) && r.request().method() === 'POST')
    await page.getByRole('button', { name: text }).click()
    const received = await response
    assert.equal(received.status(), 200)
    return received.json()
  }
  report.results.close = await submit('facts', '수치 조회하기')
  assert.equal(report.results.close.facts[0].value, manifest.close)
  assert.equal(report.results.close.facts[0].unit, 'KRW/share')
  await page.getByText('242,000 KRW/share', { exact: true }).waitFor()
  await page.getByRole('combobox').selectOption('per_ttm')
  report.results.per = await submit('facts', '수치 조회하기')
  assert.equal(report.results.per.facts[0].value, manifest.per)
  await page.getByText('9.39 x', { exact: true }).waitFor()
  report.checks.push('real_snapshot_close_and_per_match_saved_values_and_render')
  await page.getByLabel('기준일 (선택)').fill('2026-10-27')
  report.results.wrong_date = await submit('facts', '수치 조회하기')
  assert.deepEqual(report.results.wrong_date.reasons, ['fact_date_mismatch'])
  await page.getByText('요청한 날짜와 저장된 수치의 기준일이 다릅니다.').waitFor()
  assert.equal(await page.getByText('9.39 x', { exact: true }).count(), 0)
  report.checks.push('wrong_date_is_evidence_absence_not_success_or_transport_error')
  const token = await page.evaluate(() => localStorage.getItem('bb.token'))
  assert.ok(token)
  const call = async (id, suffix, body, status, authenticated = true) => {
    const response = await page.request.post(`${api}/api/debates/${id}/rag/${suffix}`, {
      data: body, headers: authenticated ? { Authorization: `Bearer ${token}` } : {},
    })
    assert.equal(response.status(), status)
    return response.json()
  }
  const repeat = await call(manifest.real_debate, 'facts', { metric: 'per_ttm', unit: 'x' }, 200)
  assert.equal(repeat.context_id, report.results.per.context_id)
  report.results.wrong_unit = await call(manifest.real_debate, 'facts', { metric: 'close', unit: 'KRW' }, 200)
  assert.deepEqual(report.results.wrong_unit.reasons, ['unit_mismatch'])
  await call(manifest.real_debate, 'facts', { metric: 'close', question: '종가' }, 400)
  await call(manifest.real_debate, 'facts', { metric: 'close' }, 401, false)
  report.results.old_snapshot_documents = await call(manifest.real_debate, 'search', { question: 'PER 의미' }, 503)
  const sealed = await page.request.get(`${api}/api/debates/${manifest.real_debate}/reveal`, { headers: { Authorization: `Bearer ${token}` } })
  assert.equal(sealed.status(), 403)
  report.checks.push('repeat_context_identity', 'wrong_unit_rejected', 'mixed_fields_400', 'unauthenticated_401', 'post_snapshot_generation_rejected_503', 'verdict_sealed_403')
  await page.goto(`${web}/debates/${manifest.evaluation_debate}`)
  await page.getByText('자료 찾아보기', { exact: true }).click()
  await page.getByLabel('찾을 내용').fill('PER 주가수익비율 의미')
  report.results.documents = await submit('search', '문서 검색하기')
  assert.equal(report.results.documents.answerability, 'documents_found')
  assert.ok(report.results.documents.documents.length > 0)
  await page.getByText(report.results.documents.documents[0].text, { exact: true }).waitFor()
  await page.getByLabel('찾을 내용').fill('zzzznoexistingterm98765')
  report.results.no_documents = await submit('search', '문서 검색하기')
  assert.equal(report.results.no_documents.answerability, 'no_documents')
  await page.getByText('조건에 맞는 문서가 없습니다. 검색어를 바꿔 보세요.').waitFor()
  report.checks.push('post_publication_fixture_document_search_renders', 'no_documents_renders')
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  assert.deepEqual(errors, [])
  assert.ok(remote.every(origin => ['https://fonts.googleapis.com', 'https://fonts.gstatic.com'].includes(origin)))
  report.blocked_external_assets = [...new Set(remote)]
  assert.ok(posts.every(path => path === '/api/auth/guest' || path.includes('/rag/')))
  assert.ok(!JSON.stringify(report.results).includes('SEALED_E2E_SENTINEL'))
  assert.equal(await page.getByText('SEALED_E2E_SENTINEL').count(), 0)
  report.checks.push('mobile_no_overflow', 'no_browser_exceptions', 'external_browser_assets_blocked', 'no_debate_start', 'no_sealed_payload')
  report.document_fixture = { snapshot_id: manifest.evaluation_snapshot, created_at: manifest.document_fixture_created_at, scope: 'separate_integration_fixture_not_original_market_snapshot' }
  await fs.writeFile(process.env.RAG_E2E_REPORT, JSON.stringify(report, null, 2))
  console.log(`Live RAG verification passed: ${report.checks.length} checks; actual HTTP and PostgreSQL/SQLite; no response mocks.`)
} finally { await browser.close() }
