import { useQuery } from '@tanstack/react-query'
import { type ReactNode, useState } from 'react'
import { Link } from 'react-router'
import { Card, ErrorNotice, Skeleton } from '../components/ui'
import { ApiError } from '../lib/api'
import { adminApi, type Day, type DebateRow, type Overview, type Period, readAdminToken, writeAdminToken } from '../lib/admin'

/**
 * 관리자 화면. 운영 중 비용·토론 상태·사용자를 한눈에 본다. 읽기 전용이고 30초마다 새로 고친다.
 * 서버 .env의 ADMIN_TOKEN을 한 번 입력하면 이 브라우저에 기억한다.
 */
export function AdminPage() {
  const [token, setToken] = useState(readAdminToken)
  if (!token) return <TokenForm onDone={setToken} />
  return (
    <Dashboard
      token={token}
      onLogout={() => {
        writeAdminToken(null)
        setToken(null)
      }}
    />
  )
}

function TokenForm({ onDone }: { onDone: (t: string) => void }) {
  const [value, setValue] = useState('')
  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-sm flex-col justify-center gap-4 px-5">
      <h1 className="text-xl font-extrabold">관리자</h1>
      <p className="text-sm text-sub">서버 .env의 ADMIN_TOKEN을 입력하세요. 이 브라우저에만 저장돼요.</p>
      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          const t = value.trim()
          if (!t) return
          writeAdminToken(t)
          onDone(t)
        }}
      >
        <input
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="관리자 토큰"
          className="min-h-12 rounded-control border border-line bg-surface px-4 text-base"
        />
        <button type="submit" className="min-h-12 rounded-control bg-point font-bold text-on-point">
          열기
        </button>
      </form>
    </div>
  )
}

const REFRESH = 30_000

function Dashboard({ token, onLogout }: { token: string; onLogout: () => void }) {
  const [days, setDays] = useState(14)
  const q = useQuery({
    queryKey: ['admin', 'overview', token, days],
    queryFn: () => adminApi.overview(token, days),
    refetchInterval: REFRESH,
    retry: false,
  })
  const unauthorized = q.error instanceof ApiError && (q.error.status === 401 || q.error.status === 404)
  const o = q.data

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-[1200px] flex-col gap-4 px-4 pb-10 pt-5 md:px-6">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-extrabold">관리자</h1>
          <p className="text-xs text-sub">
            {q.dataUpdatedAt ? `${new Date(q.dataUpdatedAt).toLocaleTimeString('ko-KR')} 기준 · 30초마다 새로 고침` : '불러오는 중'}
            {' · '}비용은 워커가 알려 준 확정값 (USD)
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => q.refetch()} className="pressable min-h-10 rounded-control bg-surface-2 px-3 text-sm font-bold">
            새로 고침
          </button>
          <button type="button" onClick={onLogout} className="pressable min-h-10 rounded-control bg-surface-2 px-3 text-sm text-sub">
            토큰 지우기
          </button>
        </div>
      </header>

      {unauthorized && <ErrorNotice message="관리자 토큰이 맞지 않거나 서버에 ADMIN_TOKEN이 없어요" />}
      {q.isError && !unauthorized && <ErrorNotice message="불러오지 못했어요" onRetry={() => q.refetch()} />}
      {!o && !q.isError && (
        <>
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </>
      )}

      {o && (
        <>
          <StatusRow o={o} />
          <Budget o={o} />
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {o.periods.map((p) => (
              <PeriodCard key={p.label} p={p} />
            ))}
          </div>
          <Daily daily={o.daily} days={days} setDays={setDays} />
          <div className="grid gap-4 lg:grid-cols-2">
            <Models o={o} />
            <Failures o={o} />
          </div>
          <Debates token={token} />
          <div className="grid gap-4 lg:grid-cols-2">
            <Users o={o} />
            <Stocks o={o} />
          </div>
          <Scoring o={o} />
        </>
      )}
    </div>
  )
}

/* ---------- 공통 ---------- */

const usd = (n: number | null | undefined, digits = 2) => (n == null ? '–' : `$${Number(n).toFixed(digits)}`)
const num = (n: number | null | undefined) => (n == null ? '–' : Number(n).toLocaleString('ko-KR'))
const tokens = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}K` : `${n}`)
const secs = (n: number | null | undefined) => {
  if (n == null) return '–'
  const s = Math.round(Number(n))
  return s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${s}초`
}
const time = (iso: string | null) => (iso ? iso.slice(5, 16).replace('T', ' ') : '–')
const rate = (hits: number, n: number) => (n ? `${Math.round((hits / n) * 100)}%` : '–')

const ORIGIN: Record<string, string> = { USER: '사용자', SCHEDULED: '전향 운용', BACKTEST: '백테스트' }
const STATUS: Record<string, { label: string; cls: string }> = {
  COMPLETED: { label: '완료', cls: 'text-ok' },
  FAILED: { label: '실패', cls: 'text-up-ink' },
  RUNNING: { label: '진행 중', cls: 'text-warn' },
}
const VERDICT: Record<string, string> = { BUY: '매수', HOLD: '보류', SELL: '매도' }

function Section({ title, sub, right, children }: { title: string; sub?: string; right?: ReactNode; children: ReactNode }) {
  return (
    <Card className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-[15px] font-extrabold">{title}</h2>
          {sub && <p className="text-xs text-sub">{sub}</p>}
        </div>
        {right}
      </div>
      {children}
    </Card>
  )
}

function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full min-w-max border-collapse text-left text-[13px] tabular-nums">
        <thead>
          <tr className="text-xs text-sub">
            {head.map((h) => (
              <th key={h} className="whitespace-nowrap border-b border-line px-2 py-1.5 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

const td = 'whitespace-nowrap border-b border-line-soft px-2 py-1.5'

/* ---------- 상태·예산 ---------- */

function StatusRow({ o }: { o: Overview }) {
  const items: [string, string][] = [
    ['서버', o.health.status],
    ['DB', o.health.db],
    ['워커', o.health.worker],
  ]
  if (o.health.forwardRun) items.push(['전향 운용', o.health.forwardRun.status])
  return (
    <div className="flex flex-wrap gap-2">
      {items.map(([k, v]) => {
        const good = v === 'UP' || v === 'FAKE' || v === 'WAITING'
        return (
          <span key={k} className={`rounded-full px-3 py-1 text-xs font-bold ${good ? 'bg-ok-soft text-ok' : 'bg-up-soft text-up-ink'}`}>
            {k} {v}
          </span>
        )
      })}
      <span className="rounded-full bg-surface-2 px-3 py-1 text-xs text-sub">워커 모드 {o.workerMode}</span>
      <span className="rounded-full bg-surface-2 px-3 py-1 text-xs text-sub">오늘 {o.today} (KST)</span>
    </div>
  )
}

function Budget({ o }: { o: Overview }) {
  const b = o.budget
  const rows: [string, typeof b.user, string?][] = [
    ['사용자 토론', b.user, `1인 하루 ${b.perUserDailyDebates}회`],
    ['전향 운용 + 단일 판정', b.scheduled, b.scheduled.enabled ? '켜짐' : '꺼짐'],
    ['백테스트', b.backtest],
  ]
  return (
    <Section title="오늘 비용 상한" sub={`사용량을 아직 모르는 토론(진행 중·실패)은 한 건에 ${usd(b.estimateUsd)}로 셈. 상한에 닿으면 새 토론을 막아요`}>
      <div className="grid gap-4 md:grid-cols-3 md:gap-8">
        {rows.map(([label, c, note]) => {
          const ratio = c.limitUsd > 0 ? Math.min(1, c.spentUsd / c.limitUsd) : 0
          const color = ratio >= 0.9 ? 'bg-up' : ratio >= 0.6 ? 'bg-warn' : 'bg-ok'
          return (
            <div key={label} className="flex flex-col gap-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-bold">{label}</span>
                <span className="text-xs text-sub">{note}</span>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-surface-2">
                <div className={`h-full rounded-full ${color}`} style={{ width: `${ratio * 100}%` }} />
              </div>
              <p className="text-xs tabular-nums text-sub">
                <span className="font-bold text-ink">{usd(c.spentUsd)}</span> / {usd(c.limitUsd, 0)} ({Math.round(ratio * 100)}%)
              </p>
            </div>
          )
        })}
      </div>
    </Section>
  )
}

function PeriodCard({ p }: { p: Period }) {
  return (
    <Card className="flex flex-col gap-2">
      <p className="text-xs font-bold text-sub">{p.label}</p>
      <p className="text-2xl font-extrabold tabular-nums">{usd(p.costUsd)}</p>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs tabular-nums">
        <Stat k="토론" v={`${num(p.debates)}건`} />
        <Stat k="완료/실패" v={`${num(p.completed)} / ${num(p.failed)}`} />
        <Stat k="1건 평균" v={usd(p.avgCostUsd, 3)} />
        <Stat k="평균 시간" v={secs(p.avgSeconds)} />
        <Stat k="판정" v={`${num(p.judgments)}건`} />
        <Stat k="진행 중" v={`${num(p.running)}건`} />
      </dl>
      {p.unknownCost > 0 && <p className="text-[11px] text-warn">비용 미확정 {p.unknownCost}건 (합계에서 빠짐)</p>}
    </Card>
  )
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex min-w-0 flex-col">
      <dt className="text-sub">{k}</dt>
      <dd className="truncate font-bold">{v}</dd>
    </div>
  )
}

/* ---------- 일별 ---------- */

const SERIES = [
  { key: 'userUsd', label: '사용자', cls: 'bg-point' },
  { key: 'scheduledUsd', label: '전향 운용', cls: 'bg-mod' },
  { key: 'backtestUsd', label: '백테스트', cls: 'bg-down' },
] as const

function Daily({ daily, days, setDays }: { daily: Day[]; days: number; setDays: (d: number) => void }) {
  const total = (d: Day) => Number(d.userUsd) + Number(d.scheduledUsd) + Number(d.backtestUsd)
  const max = Math.max(0.01, ...daily.map(total))
  const sum = daily.reduce((a, d) => a + total(d), 0)
  return (
    <Section
      title="일별 비용"
      sub={`${days}일 합계 ${usd(sum)} · 막대 위 숫자는 토론 수`}
      right={
        <div className="flex gap-1">
          {[7, 14, 30].map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={`min-h-8 rounded-control px-2.5 text-xs font-bold ${days === d ? 'bg-point text-on-point' : 'bg-surface-2 text-sub'}`}
            >
              {d}일
            </button>
          ))}
        </div>
      }
    >
      <div className="flex gap-3 text-xs text-sub">
        {SERIES.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5">
            <span className={`size-2.5 rounded-sm ${s.cls}`} />
            {s.label}
          </span>
        ))}
      </div>
      <div className="flex h-44 items-end gap-1">
        {daily.map((d) => {
          const t = total(d)
          return (
            <div key={d.day} className="group relative flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1">
              {d.debates > 0 && <span className="text-[10px] tabular-nums text-sub">{d.debates}</span>}
              <div className="flex w-full max-w-8 flex-col-reverse overflow-hidden rounded-t" style={{ height: `${(t / max) * 100}%` }}>
                {SERIES.map((s) => (
                  <div key={s.key} className={s.cls} style={{ height: t ? `${(Number(d[s.key]) / t) * 100}%` : 0 }} />
                ))}
              </div>
              <span className="text-[10px] tabular-nums text-faint">{d.day.slice(8)}</span>
              <div className="pointer-events-none absolute bottom-full z-10 mb-1 hidden w-max rounded-control bg-surface-2 px-2.5 py-1.5 text-[11px] leading-relaxed shadow-lg group-hover:block">
                <p className="font-bold">{d.day}</p>
                <p>합계 {usd(t, 3)} · 토론 {d.debates} (실패 {d.failed})</p>
                <p className="text-sub">사용자 {usd(d.userUsd, 3)} · 전향 {usd(d.scheduledUsd, 3)} · 백테스트 {usd(d.backtestUsd, 3)}</p>
                <p className="text-sub">판정 {d.judgments}</p>
              </div>
            </div>
          )
        })}
      </div>
    </Section>
  )
}

/* ---------- 모델·실패 ---------- */

function Models({ o }: { o: Overview }) {
  return (
    <Section title="모델별 토큰 (최근 30일)" sub="캐시 적중 = 캐시 읽기 ÷ 전체 입력. 높을수록 싸요">
      {o.models.length === 0 ? (
        <p className="text-sm text-sub">아직 사용량이 없어요</p>
      ) : (
        <Table head={['모델', '토론', '입력', '캐시 읽기', '캐시 쓰기', '출력', '캐시 적중']}>
          {o.models.map((m) => {
            const all = Number(m.inputTokens) + Number(m.cacheReadTokens) + Number(m.cacheWriteTokens)
            return (
              <tr key={m.model}>
                <td className={td}>{m.model}</td>
                <td className={td}>{m.debates}</td>
                <td className={td}>{tokens(Number(m.inputTokens))}</td>
                <td className={td}>{tokens(Number(m.cacheReadTokens))}</td>
                <td className={td}>{tokens(Number(m.cacheWriteTokens))}</td>
                <td className={td}>{tokens(Number(m.outputTokens))}</td>
                <td className={`${td} font-bold`}>{rate(Number(m.cacheReadTokens), all)}</td>
              </tr>
            )
          })}
        </Table>
      )}
    </Section>
  )
}

function Failures({ o }: { o: Overview }) {
  return (
    <Section title="실패 원인 (최근 7일)">
      {o.failures.length === 0 ? (
        <p className="text-sm text-sub">실패한 토론이 없어요</p>
      ) : (
        <Table head={['코드', '건수', '마지막', '메시지']}>
          {o.failures.map((f) => (
            <tr key={f.code}>
              <td className={`${td} font-bold text-up-ink`}>{f.code}</td>
              <td className={td}>{f.count}</td>
              <td className={td}>{time(f.lastAt)}</td>
              <td className={`${td} max-w-72 truncate text-sub`} title={f.message ?? ''}>
                {f.message}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Section>
  )
}

/* ---------- 토론 목록·상세 ---------- */

function Debates({ token }: { token: string }) {
  const [status, setStatus] = useState('')
  const [origin, setOrigin] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['admin', 'debates', token, status, origin],
    queryFn: () => adminApi.debates(token, status, origin),
    refetchInterval: REFRESH,
  })
  const select = 'min-h-8 rounded-control border border-line bg-surface-2 px-2 text-xs'
  return (
    <Section
      title="최근 토론"
      sub="줄을 누르면 단계별 시간과 사용량을 볼 수 있어요"
      right={
        <div className="flex gap-2">
          <select aria-label="상태" value={status} onChange={(e) => setStatus(e.target.value)} className={select}>
            <option value="">모든 상태</option>
            <option value="RUNNING">진행 중</option>
            <option value="COMPLETED">완료</option>
            <option value="FAILED">실패</option>
          </select>
          <select aria-label="출처" value={origin} onChange={(e) => setOrigin(e.target.value)} className={select}>
            <option value="">모든 출처</option>
            <option value="USER">사용자</option>
            <option value="SCHEDULED">전향 운용</option>
            <option value="BACKTEST">백테스트</option>
          </select>
        </div>
      }
    >
      {q.isError && <ErrorNotice message="토론 목록을 불러오지 못했어요" onRetry={() => q.refetch()} />}
      {!q.data && !q.isError && <Skeleton className="h-40 w-full" />}
      {q.data && q.data.length === 0 && <p className="text-sm text-sub">토론이 없어요</p>}
      {q.data && q.data.length > 0 && (
        <Table head={['시작', '종목', '출처', '상태', '걸린 시간', '비용', '토큰 입력/출력', 'AI 판정', '판정 수', '요청자']}>
          {q.data.map((d) => (
            <DebateLine key={d.id} d={d} open={open === d.id} onToggle={() => setOpen(open === d.id ? null : d.id)} token={token} />
          ))}
        </Table>
      )}
    </Section>
  )
}

function DebateLine({ d, open, onToggle, token }: { d: DebateRow; open: boolean; onToggle: () => void; token: string }) {
  const s = STATUS[d.status] ?? { label: d.status, cls: '' }
  return (
    <>
      <tr onClick={onToggle} className={`cursor-pointer hover:bg-surface-2 ${open ? 'bg-surface-2' : ''}`}>
        <td className={td}>{time(d.createdAt)}</td>
        <td className={td}>
          <span className="font-bold">{d.name}</span> <span className="text-faint">{d.ticker}</span>
        </td>
        <td className={td}>{ORIGIN[d.origin] ?? d.origin}</td>
        <td className={`${td} font-bold ${s.cls}`} title={d.error ?? ''}>
          {s.label}
        </td>
        <td className={td}>{secs(d.seconds)}</td>
        <td className={`${td} font-bold`}>{usd(d.costUsd, 3)}</td>
        <td className={td}>
          {d.inputTokens == null ? '–' : `${tokens(Number(d.inputTokens))} / ${tokens(Number(d.outputTokens ?? 0))}`}
        </td>
        <td className={td}>{d.verdict ? `${VERDICT[d.verdict] ?? d.verdict} ${Math.round(Number(d.confidence) * 100)}%` : '–'}</td>
        <td className={td}>{d.judgments}</td>
        <td className={`${td} text-sub`}>{d.requesterNickname ?? (d.requesterId ? `${d.requesterGuest ? '게스트' : '회원'} #${d.requesterId.slice(0, 4)}` : '–')}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={10} className="border-b border-line bg-surface-2 p-3">
            <DebateDetailView id={d.id} token={token} />
          </td>
        </tr>
      )}
    </>
  )
}

const EVENT: Record<string, string> = {
  snapshot_created: '자료 수집 완료',
  turn_started: '발언 시작',
  tool_call: '자료 조회',
  statement_rejected: '형식 실패 · 다시 씀',
  statement_accepted: '발언 확정',
  extra_round_requested: '추가 질문',
  moderator_started: '중재자 평가 시작',
  debate_completed: '토론 완료',
  debate_failed: '토론 실패',
  debate_sealed: '판정 봉인',
}
const SIDE: Record<string, string> = { bull: '매수', bear: '매도' }
const ROUND: Record<string, string> = { opening: '입론', rebuttal: '반박', closing: '최종변론', extra: '추가' }

function DebateDetailView({ id, token }: { id: string; token: string }) {
  const q = useQuery({ queryKey: ['admin', 'debate', token, id], queryFn: () => adminApi.debate(token, id) })
  if (q.isError) return <p className="text-sm text-up-ink">상세를 불러오지 못했어요</p>
  if (!q.data) return <Skeleton className="h-24 w-full" />
  const d = q.data
  const start = d.events.length ? new Date(d.events[0].at).getTime() : 0
  let usage: { calls?: { model: string; input_tokens?: number; output_tokens?: number; cache_read_input_tokens?: number; cache_creation_input_tokens?: number }[]; cost_usd?: number } | null = null
  try {
    usage = d.usage ? JSON.parse(d.usage) : null
  } catch {
    usage = null
  }
  return (
    <div className="grid gap-4 text-xs md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-1">
        <p className="font-bold">단계별 시간 (시작 기준 +초)</p>
        <ol className="flex max-h-72 flex-col gap-0.5 overflow-y-auto tabular-nums">
          {d.events.map((e) => (
            <li key={e.seq} className="flex gap-2">
              <span className="w-12 shrink-0 text-right text-faint">+{Math.round((new Date(e.at).getTime() - start) / 1000)}</span>
              <span className={e.type === 'statement_rejected' || e.type === 'debate_failed' ? 'text-up-ink' : ''}>
                {EVENT[e.type] ?? e.type}
                {e.side && ` · ${SIDE[e.side] ?? e.side}`}
                {e.round && ` ${ROUND[e.round] ?? e.round}`}
                {e.attempt && ` (${e.attempt}번째)`}
                {e.tool && ` · ${e.tool}`}
              </span>
            </li>
          ))}
        </ol>
      </div>
      <div className="flex flex-col gap-3">
        {d.error && <p className="text-up-ink">실패: {d.error}</p>}
        {usage?.calls && (
          <div className="flex flex-col gap-1">
            <p className="font-bold">사용량 {usage.cost_usd != null && `· ${usd(usage.cost_usd, 4)}`}</p>
            {usage.calls.map((c) => (
              <p key={c.model} className="tabular-nums text-sub">
                {c.model}: 입력 {tokens(c.input_tokens ?? 0)} · 캐시 읽기 {tokens(c.cache_read_input_tokens ?? 0)} · 캐시 쓰기 {tokens(c.cache_creation_input_tokens ?? 0)} · 출력 {tokens(c.output_tokens ?? 0)}
              </p>
            ))}
          </div>
        )}
        <div className="flex flex-col gap-1">
          <p className="font-bold">사용자 판정 {d.judgmentList.length}건</p>
          {d.judgmentList.map((j, i) => (
            <p key={i} className="text-sub">
              {time(j.at)} · {j.nickname ?? '익명'} · {VERDICT[j.decision] ?? j.decision} {j.confidence}%
            </p>
          ))}
        </div>
        <Link to={`/debates/${d.id}`} className="font-bold text-point">
          토론 화면 열기 →
        </Link>
      </div>
    </div>
  )
}

/* ---------- 사용자·종목·채점 ---------- */

function Users({ o }: { o: Overview }) {
  const u = o.users
  return (
    <Section title="사용자" sub={`전체 ${num(u.total)}명 · 카카오 ${num(u.members)} · 게스트 ${num(u.guests)} · 닉네임 ${num(u.withNickname)}`}>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <Stat k="오늘 새로 온 사람" v={`${num(u.newToday)}명`} />
        <Stat k="오늘 판정한 사람" v={`${num(u.activeToday)}명`} />
      </div>
      {u.top.length > 0 && (
        <Table head={['이름', '판정', '7일 채점', '적중', '마지막']}>
          {u.top.map((t) => (
            <tr key={t.userId}>
              <td className={td}>{t.nickname ?? `${t.guest ? '게스트' : '회원'} #${t.userId.slice(0, 4)}`}</td>
              <td className={td}>{t.judgments}</td>
              <td className={td}>{t.scored}</td>
              <td className={td}>{rate(t.hits, t.scored)}</td>
              <td className={td}>{time(t.lastAt)}</td>
            </tr>
          ))}
        </Table>
      )}
    </Section>
  )
}

function Stocks({ o }: { o: Overview }) {
  return (
    <Section title="많이 토론한 종목">
      {o.stocks.length === 0 ? (
        <p className="text-sm text-sub">아직 없어요</p>
      ) : (
        <Table head={['종목', '토론', '비용', '판정', '마지막']}>
          {o.stocks.map((s) => (
            <tr key={s.ticker}>
              <td className={td}>
                <span className="font-bold">{s.name}</span> <span className="text-faint">{s.ticker}</span>
              </td>
              <td className={td}>{s.debates}</td>
              <td className={td}>{usd(s.costUsd, 3)}</td>
              <td className={td}>{s.judgments}</td>
              <td className={td}>{time(s.lastAt)}</td>
            </tr>
          ))}
        </Table>
      )}
    </Section>
  )
}

function Scoring({ o }: { o: Overview }) {
  return (
    <Section title="채점 현황" sub="같은 판정 묶음에서 사용자와 AI 중재자의 적중률. 자세한 실험 결과는 AI 성적표">
      {o.scoring.length === 0 ? (
        <p className="text-sm text-sub">아직 채점할 판정이 없어요</p>
      ) : (
        <Table head={['기간', '채점 끝', '대기', '사용자 적중', 'AI 적중']}>
          {o.scoring.map((s) => (
            <tr key={s.days}>
              <td className={td}>{s.days}거래일</td>
              <td className={td}>{s.scored}</td>
              <td className={td}>{s.pending}</td>
              <td className={`${td} font-bold`}>{rate(s.userHits, s.scored)}</td>
              <td className={`${td} font-bold`}>{rate(s.moderatorHits, s.scored)}</td>
            </tr>
          ))}
        </Table>
      )}
      <Link to="/report" className="text-xs font-bold text-point">
        AI 성적표 열기 →
      </Link>
    </Section>
  )
}
