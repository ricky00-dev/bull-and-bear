export const won = (n: number) => `${Math.round(n).toLocaleString('ko-KR')}원`

export const pct = (n: number, signed = true) => `${signed && n > 0 ? '+' : ''}${n.toFixed(2)}%`

/** 상승 빨강, 하락 파랑 */
export const changeColor = (n: number) => (n > 0 ? 'text-up-ink' : n < 0 ? 'text-down-ink' : 'text-sub')

/** %p (초과수익) */
export const pctPoint = (n: number) => `${n > 0 ? '+' : ''}${n.toFixed(2)}%p`

/** '2026-10-27' → '10/27' */
export const monthDay = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`

/** 큰 금액을 조·억 단위로 */
export function bigWon(n: number): string {
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(1)}조원`
  if (abs >= 1e8) return `${sign}${Math.round(abs / 1e8).toLocaleString('ko-KR')}억원`
  return won(n)
}

/** 오늘(KST) 'YYYY-MM-DD' */
export const todayKst = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' })

/** 채점 예정일 안내. 예정일이 지났는데 아직 채점 전이면(시세 대기·휴장) 날짜 대신 "곧" */
export const dueLabel = (iso: string) => (iso < todayKst() ? '곧 채점' : `${monthDay(iso)} 채점 예정`)
