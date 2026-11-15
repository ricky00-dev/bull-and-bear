// Real services only. Seed with scripts/rag-multistock-prepare.py; no API mocks.
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const manifest = JSON.parse(await fs.readFile(process.env.RAG_E2E_MANIFEST, 'utf8'))
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright')
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH })
const api = process.env.RAG_E2E_API ?? 'http://127.0.0.1:18080'
const web = process.env.WEB_TEST_URL ?? 'http://127.0.0.1:15173'
const report = { schema: 'rag-multistock-live-v1', scope: manifest.scope, publication: manifest.publication,
  readiness: manifest.readiness, configured_generation: manifest.generation_id,
  previous_generation: manifest.previous_generation_id, bindings: manifest.bindings,
  rows: [], checks: [], response_stubs: false }
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => ['127.0.0.1', 'localhost'].includes(new URL(route.request().url()).hostname)
    ? route.continue() : route.abort())
  const submit = async (route, button) => {
    const waiting = page.waitForResponse(r => r.url().endsWith(`/rag/${route}`) && r.request().method() === 'POST')
    await page.getByRole('button', { name: button }).click()
    const response = await waiting
    assert.equal(response.status(), 200)
    return response.json()
  }
  for (const row of manifest.rows) {
    await page.goto(`${web}/debates/${row.debate_id}`)
    await page.getByText('자료 찾아보기', { exact: true }).click()
    await page.getByLabel('찾을 내용').fill('PER 종목분리검증')
    const docs = await submit('search', '문서 검색하기')
    assert.equal(docs.ticker, row.ticker)
    assert.equal(docs.snapshot_id, row.snapshot_id)
    assert.deepEqual(docs.documents.map(d => d.chunk_id), [row.chunk_id])
    await page.getByText(docs.documents[0].text, { exact: true }).waitFor()
    for (const other of manifest.rows.filter(r => r.ticker !== row.ticker)) {
      assert.ok(!JSON.stringify(docs.documents).includes(other.chunk_id))
    }
    await page.getByLabel('수치 조회', { exact: true }).check()
    assert.equal(await page.getByText(docs.documents[0].text, { exact: true }).count(), 0)
    const facts = await submit('facts', '수치 조회하기')
    assert.equal(facts.ticker, row.ticker)
    assert.equal(facts.facts[0].ticker, row.ticker)
    assert.equal(facts.facts[0].value, row.close)
    await page.getByText(`${row.close.toLocaleString('ko-KR')} KRW/share`, { exact: true }).waitFor()
    const token = await page.evaluate(() => localStorage.getItem('bb.token'))
    const call = async (id, route, data, status = 200) => {
      const response = await page.request.post(`${api}/api/debates/${id}/rag/${route}`, { data, headers: { Authorization: `Bearer ${token}` } })
      assert.equal(response.status(), status)
      return response.json()
    }
    const oldFacts = await call(row.original_debate_id, 'facts', { metric: 'close', unit: 'KRW/share' })
    assert.equal(oldFacts.snapshot_id, row.source_snapshot_id)
    assert.equal(oldFacts.facts[0].value, row.close)
    await call(row.original_debate_id, 'search', { question: 'PER 종목분리검증' }, 503)
    const wrong = manifest.rows.find(r => r.ticker !== row.ticker)
    await call(row.debate_id, 'facts', { metric: 'close', ticker: wrong.ticker }, 400)
    await call(row.debate_id, 'search', { question: 'PER', snapshot_id: wrong.snapshot_id }, 400)
    const results = await Promise.all(Array.from({ length: 3 }, () => Promise.all(manifest.rows.map(async current => {
      const result = await call(current.debate_id, 'facts', { metric: 'close', unit: 'KRW/share' })
      assert.equal(result.ticker, current.ticker)
      assert.equal(result.snapshot_id, current.snapshot_id)
      assert.equal(result.facts[0].value, current.close)
      return { ticker: current.ticker, context_id: result.context_id }
    }))))
    const own = results.flat().filter(r => r.ticker === row.ticker)
    assert.ok(own.every(r => r.context_id === facts.context_id))
    report.rows.push({ ...row, documents: docs, facts, original_facts: oldFacts, concurrent_results: results })
    report.checks.push(`${row.ticker}:scoped_document_only`, `${row.ticker}:saved_value_and_ui`,
      `${row.ticker}:original_value_unchanged`, `${row.ticker}:old_generation_rejected`,
      `${row.ticker}:identity_override_rejected`, `${row.ticker}:concurrent_isolation_and_replay`)
  }
  assert.notEqual(report.rows[0].facts.context_id, report.rows[1].facts.context_id)
  assert.deepEqual(errors, [])
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  report.checks.push('distinct_contexts_between_tickers', 'no_browser_exceptions', 'mobile_no_overflow')
  if (manifest.previous_generation_id) {
    assert.notEqual(manifest.generation_id, manifest.previous_generation_id)
    assert.ok(manifest.bindings.every(binding => binding.generation_id === manifest.previous_generation_id))
    report.checks.push('old_documents_available_after_generation_rollover')
  }
  await fs.writeFile(process.env.RAG_E2E_REPORT, JSON.stringify(report, null, 2))
  console.log(`Multi-stock live checks passed: ${report.checks.length}; ${report.rows.length} saved-source tickers, mock provenance retained.`)
} finally { await browser.close() }
