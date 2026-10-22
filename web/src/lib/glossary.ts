import { bigWon, pct, won } from './format'

/**
 * 근거 ID(스냅샷 Fact ID) → 입문자용 이름·설명·값 표기.
 * 근거 칩을 누르면 이 설명이 시트로 뜬다. 지표를 배우는 화면이라 설명 문장이 중요하다.
 */
interface Entry {
  label: string
  desc: string
  format: (v: number) => string
}

const signedPct = (v: number) => pct(v)
const plainPct = (v: number) => pct(v, false)
const times = (v: number) => `${v.toFixed(2)}배`

const ENTRIES: Record<string, Entry> = {
  'PX.CLOSE': { label: '종가', desc: '그날 마지막으로 거래된 가격이에요.', format: won },
  'PX.CHG_1D': { label: '전일 대비', desc: '어제 종가보다 얼마나 움직였는지예요.', format: signedPct },
  'PX.RET_1M': { label: '1개월 수익률', desc: '약 한 달(21거래일) 전 종가 대비 상승률이에요.', format: signedPct },
  'PX.RET_3M': { label: '3개월 수익률', desc: '약 석 달 전 종가 대비 상승률이에요.', format: signedPct },
  'PX.RET_6M': { label: '6개월 수익률', desc: '약 반년 전 종가 대비 상승률이에요.', format: signedPct },
  'PX.RET_1Y': { label: '1년 수익률', desc: '1년 전 종가와 비교해 얼마나 올랐는지예요. 길게 보면 오르는 추세인지 판단할 때 써요.', format: signedPct },
  'PX.HIGH_52W': { label: '52주 최고가', desc: '최근 1년 동안 가장 비쌌던 가격이에요.', format: won },
  'PX.LOW_52W': { label: '52주 최저가', desc: '최근 1년 동안 가장 쌌던 가격이에요.', format: won },
  'PX.FROM_HIGH_52W': { label: '52주 최고가 대비', desc: '최근 1년 중 가장 비쌌던 가격에서 지금 얼마나 내려왔는지예요. 많이 빠졌다고 꼭 싼 건 아니에요.', format: signedPct },
  'PX.FROM_LOW_52W': { label: '52주 최저가 대비', desc: '최근 1년 중 가장 쌌던 가격보다 지금 얼마나 높은지예요.', format: signedPct },
  'PX.MA20': { label: '20일 이동평균', desc: '최근 20거래일 종가의 평균이에요.', format: won },
  'PX.MA60': { label: '60일 이동평균', desc: '최근 60거래일 종가의 평균이에요.', format: won },
  'PX.MA120': { label: '120일 이동평균', desc: '최근 120거래일(약 반년) 종가의 평균이에요.', format: won },
  'PX.VS_MA20': { label: '20일 이동평균 대비', desc: '최근 20거래일 평균 가격보다 지금 가격이 얼마나 높거나 낮은지예요. 짧은 추세를 볼 때 써요.', format: signedPct },
  'PX.VS_MA60': { label: '60일 이동평균 대비', desc: '최근 60거래일 평균보다 얼마나 높거나 낮은지예요.', format: signedPct },
  'PX.VS_MA120': { label: '120일 이동평균 대비', desc: '최근 반년 평균보다 얼마나 높거나 낮은지예요. 20·60·120일 평균을 모두 밑돌면 하락 추세로 보는 경우가 많아요.', format: signedPct },
  'PX.VOL_20D': { label: '20일 변동성', desc: '하루하루 가격이 얼마나 들쭉날쭉했는지 1년 기준으로 바꾼 값이에요. 높을수록 위아래로 크게 움직여요.', format: plainPct },
  'PX.AVG_VOLUME_20D': { label: '20일 평균 거래량', desc: '최근 20거래일 동안 하루 평균 거래된 주식 수예요.', format: (v) => `${Math.round(v).toLocaleString('ko-KR')}주` },
  'PX.VOLUME_RATIO': { label: '거래량 / 20일 평균', desc: '오늘 거래량이 평소(20일 평균)의 몇 배인지예요. 크게 떨어지는 날 거래량까지 많으면 한꺼번에 파는 투매로 봐요.', format: times },
  'VAL.MKTCAP': { label: '시가총액', desc: '주가 × 주식 수. 회사 전체를 지금 가격에 사려면 드는 돈이에요.', format: bigWon },
  'VAL.PER_TTM': { label: 'PER', desc: '시가총액을 최근 1년 순이익으로 나눈 값이에요. 이익에 비해 주가가 비싼지 싼지 볼 때 써요.', format: times },
  'VAL.PBR': { label: 'PBR', desc: '시가총액을 회사 순자산(자본)으로 나눈 값이에요. 1보다 낮으면 장부상 가치보다 싸게 거래된다는 뜻이에요.', format: times },
  'VAL.ROE_TTM': { label: 'ROE', desc: '자본으로 1년 동안 얼마나 이익을 냈는지예요. 높을수록 돈을 잘 버는 회사예요.', format: plainPct },
  'VAL.DEBT_RATIO': { label: '부채비율', desc: '부채를 자본으로 나눈 값이에요. 높을수록 빚에 기대는 정도가 커요.', format: plainPct },
  'VAL.OP_MARGIN_TTM': { label: '영업이익률', desc: '매출에서 본업으로 남긴 이익의 비율이에요.', format: plainPct },
}

const PREFIX: Record<string, { label: string; desc: string }> = {
  FIN: { label: '재무제표', desc: 'DART 정기보고서의 재무 수치예요.' },
  VAL: { label: '밸류에이션', desc: '주가와 재무 수치로 계산한 지표예요.' },
  NEWS: { label: '뉴스', desc: '스냅샷 시점까지 나온 기사예요. 기사 속 전망은 사실이 아니라 의견이에요.' },
  DISC: { label: '공시', desc: '회사가 DART에 제출한 공식 보고서예요.' },
}

export function describe(sourceId: string): { label: string; desc: string } {
  const e = ENTRIES[sourceId]
  if (e) return { label: e.label, desc: e.desc }
  return PREFIX[sourceId.split('.')[0]] ?? { label: sourceId, desc: '' }
}

export function formatValue(sourceId: string, value: number | null): string {
  if (value === null) return ''
  const e = ENTRIES[sourceId]
  if (e) return e.format(value)
  return sourceId.startsWith('FIN.') ? bigWon(value) : value.toLocaleString('ko-KR')
}

/** 칩에 쓰는 짧은 문구: "120일 이동평균 대비 −21.59%" */
export function chipText(sourceId: string, value: number | null): string {
  const v = formatValue(sourceId, value)
  return v ? `${describe(sourceId).label} ${v}` : describe(sourceId).label
}
