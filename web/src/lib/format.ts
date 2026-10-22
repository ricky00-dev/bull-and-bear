export const won = (n: number) => `${Math.round(n).toLocaleString('ko-KR')}원`

export const pct = (n: number, signed = true) => `${signed && n > 0 ? '+' : ''}${n.toFixed(2)}%`

/** 상승 빨강, 하락 파랑 */
export const changeColor = (n: number) => (n > 0 ? 'text-up' : n < 0 ? 'text-down-ink' : 'text-sub')

/** 큰 금액을 조·억 단위로 */
export function bigWon(n: number): string {
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(1)}조원`
  if (abs >= 1e8) return `${sign}${Math.round(abs / 1e8).toLocaleString('ko-KR')}억원`
  return won(n)
}
