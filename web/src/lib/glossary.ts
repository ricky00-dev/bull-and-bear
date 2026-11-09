import { bigWon, pct, pctPoint, won } from './format'

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
  'VAL.REVENUE_TTM': { label: '매출(최근 4분기)', desc: '최근 4개 분기 매출을 더한 금액이에요. 1년치 장사 규모예요.', format: bigWon },
  'VAL.OPERATING_INCOME_TTM': { label: '영업이익(최근 4분기)', desc: '최근 4개 분기 영업이익을 더한 금액이에요. 본업으로 1년 동안 번 돈이에요.', format: bigWon },
  'VAL.NET_INCOME_TTM': { label: '순이익(최근 4분기)', desc: '최근 4개 분기 순이익을 더한 금액이에요. PER·ROE를 계산할 때 쓰여요.', format: bigWon },
  'VAL.SHARES': { label: '발행주식수', desc: '회사가 발행한 보통주 수예요. 주가에 곱하면 시가총액이 돼요.', format: (v) => `${Math.round(v).toLocaleString('ko-KR')}주` },
  // 새 엔진(#44)의 코스피 비교 근거. 3·7·21거래일
  ...periodEntries(),
}

function periodEntries(): Record<string, Entry> {
  const out: Record<string, Entry> = {}
  for (const n of [3, 7, 21]) {
    out[`PX.RET_${n}D`] = { label: `${n}거래일 수익률`, desc: `최근 ${n}거래일 동안 이 종목 주가가 얼마나 움직였는지예요.`, format: signedPct }
    out[`MKT.KOSPI_RET_${n}D`] = { label: `코스피 ${n}거래일 수익률`, desc: `같은 ${n}거래일 동안 코스피 지수가 얼마나 움직였는지예요. 시장 전체 흐름이에요.`, format: signedPct }
    out[`PX.EXCESS_KOSPI_${n}D`] = {
      label: `코스피 대비 ${n}거래일`,
      desc: `같은 ${n}거래일 동안 이 종목 수익률에서 코스피 수익률을 뺀 값이에요. +면 시장보다 잘했고, −면 시장보다 못했어요. 채점도 이 기준(코스피 대비)으로 해요.`,
      format: pctPoint,
    }
  }
  return out
}

const PREFIX: Record<string, { label: string; desc: string }> = {
  FIN: { label: '재무제표', desc: 'DART 정기보고서의 재무 수치예요.' },
  VAL: { label: '밸류에이션', desc: '주가와 재무 수치로 계산한 지표예요.' },
  NEWS: { label: '뉴스', desc: '스냅샷 시점까지 나온 기사예요. 기사 속 전망은 사실이 아니라 의견이에요.' },
  MKT: { label: '시장', desc: '코스피 같은 시장 전체 지표예요.' },
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

/**
 * 칩에 쓰는 짧은 문구: "120일 이동평균 대비 −21.59%".
 * 뉴스·공시처럼 값이 없는 근거는 제목(새 엔진의 observation.label)을 붙인다: "뉴스 · 외국인 순매도 이어져"
 */
export function chipText(sourceId: string, value: number | null, title?: string | null): string {
  const v = formatValue(sourceId, value)
  const { label } = describe(sourceId)
  if (v) return `${label} ${v}`
  const t = title?.trim()
  return t && t !== label ? `${label} · ${t.length > 28 ? `${t.slice(0, 27)}…` : t}` : label
}

/**
 * 토론 본문에 나오는 투자 용어. 본문에서 찾아 밑줄을 긋고, 누르면 이 설명을 띄운다.
 * words 중 하나라도 본문에 있으면 걸린다. 긴 단어를 먼저 찾으므로 "120일선"이 "120일"보다 우선한다.
 */
export interface Term {
  label: string
  desc: string
  words: string[]
}

export const TERMS: Term[] = [
  { label: 'PER', words: ['PER', '주가수익비율'], desc: ENTRIES['VAL.PER_TTM'].desc + ' 같은 업종끼리 비교해야 의미가 있어요.' },
  { label: 'PBR', words: ['PBR', '주가순자산비율'], desc: ENTRIES['VAL.PBR'].desc },
  { label: 'ROE', words: ['ROE', '자기자본이익률'], desc: ENTRIES['VAL.ROE_TTM'].desc },
  { label: '시가총액', words: ['시가총액', '시총'], desc: ENTRIES['VAL.MKTCAP'].desc },
  { label: '부채비율', words: ['부채비율'], desc: ENTRIES['VAL.DEBT_RATIO'].desc },
  { label: '영업이익률', words: ['영업이익률'], desc: ENTRIES['VAL.OP_MARGIN_TTM'].desc },
  { label: '영업이익', words: ['영업이익'], desc: '매출에서 원가·인건비 같은 본업 비용을 빼고 남은 이익이에요. 회사가 본업으로 얼마나 버는지 보여줘요.' },
  { label: '순이익', words: ['당기순이익', '순이익'], desc: '영업이익에서 이자·세금 같은 비용까지 모두 빼고 최종으로 남은 이익이에요.' },
  { label: '매출', words: ['매출액', '매출'], desc: '물건이나 서비스를 팔아 들어온 돈 전체예요. 비용을 빼기 전 금액이에요.' },
  { label: '실적', words: ['실적'], desc: '회사가 일정 기간 동안 낸 매출과 이익 성적표예요. 보통 분기(3개월)마다 발표해요.' },
  { label: '밸류에이션', words: ['밸류에이션'], desc: '회사의 가치에 비해 주가가 비싼지 싼지 따져보는 일이에요. PER·PBR 같은 지표를 써요.' },
  { label: '저평가', words: ['저평가'], desc: '회사가 버는 돈이나 가진 자산에 비해 주가가 싸다는 뜻이에요. 싼 데는 이유가 있을 수도 있어요.' },
  { label: '고평가', words: ['고평가', '밸류 부담', '밸류에이션 부담'], desc: '회사가 버는 돈이나 가진 자산에 비해 주가가 비싸다는 뜻이에요. 앞으로의 기대가 이미 주가에 많이 반영됐다는 의미이기도 해요.' },
  { label: '이동평균선', words: ['이동평균선', '이동평균', '이평선', '20일선', '60일선', '120일선'], desc: '최근 며칠 동안 종가의 평균을 이은 선이에요. 주가가 이 선 위에 있으면 오르는 흐름, 아래에 있으면 내리는 흐름으로 많이 봐요.' },
  { label: '추세', words: ['상승 추세', '하락 추세', '추세'], desc: '주가가 한동안 한쪽 방향으로 움직이는 흐름이에요. 추세가 꼭 이어진다는 보장은 없어요.' },
  { label: '모멘텀', words: ['모멘텀'], desc: '주가가 움직이는 힘이에요. 최근 많이 오른 주식이 한동안 더 오르는 경향을 말할 때 써요.' },
  { label: '반등', words: ['기술적 반등', '반등'], desc: '떨어지던 주가가 다시 오르는 것이에요. 잠깐 오르고 다시 내리는 경우도 많아요.' },
  { label: '과매도', words: ['과매도'], desc: '짧은 기간에 너무 많이 팔려서 주가가 지나치게 떨어졌다는 뜻이에요. 반등을 기대하는 근거로 쓰여요.' },
  { label: '과매수', words: ['과매수', '과열'], desc: '짧은 기간에 너무 많이 사들여서 주가가 지나치게 올랐다는 뜻이에요.' },
  { label: '투매', words: ['투매'], desc: '겁을 먹고 가격을 따지지 않고 한꺼번에 파는 것이에요. 주가가 크게 떨어지면서 거래량이 확 늘어요.' },
  { label: '거래량', words: ['거래량'], desc: '하루 동안 사고팔린 주식 수예요. 가격이 움직일 때 거래량도 많으면 그 움직임을 더 믿을 만하다고 봐요.' },
  { label: '변동성', words: ['변동성'], desc: '주가가 위아래로 얼마나 크게 흔들리는지예요. 높을수록 크게 벌 수도, 크게 잃을 수도 있어요.' },
  { label: '52주 최고가·최저가', words: ['52주 최고가', '52주 최저가', '52주 신고가', '52주 신저가'], desc: '최근 1년 동안 가장 비쌌던 가격과 가장 쌌던 가격이에요.' },
  { label: '지지선', words: ['지지선'], desc: '주가가 떨어지다가 자주 멈추고 다시 오르던 가격대예요. 여기를 깨고 내려가면 더 떨어진다고 보는 사람이 많아요.' },
  { label: '저항선', words: ['저항선'], desc: '주가가 오르다가 자주 막히던 가격대예요. 여기를 뚫으면 더 오른다고 보는 사람이 많아요.' },
  { label: '코스피', words: ['코스피', 'KOSPI'], desc: '우리나라 대표 주식시장, 또는 그 시장 전체 주가를 하나로 나타낸 지수예요. 우리 서비스는 종목이 코스피보다 잘했는지로 채점해요.' },
  { label: '코스닥', words: ['코스닥', 'KOSDAQ'], desc: '중소·기술 기업이 주로 있는 우리나라 두 번째 주식시장이에요.' },
  { label: '초과수익', words: ['초과수익', '초과 수익'], desc: '종목 수익률에서 코스피 수익률을 뺀 값이에요. 시장 전체보다 얼마나 더 잘했는지 보여줘요.' },
  { label: '%p', words: ['%p', '퍼센트포인트'], desc: '퍼센트끼리의 차이예요. 3%와 5%의 차이는 2%p예요.' },
  { label: '전년 동기 대비', words: ['전년 동기 대비', '전년 대비', 'YoY'], desc: '작년 같은 기간과 비교한 변화예요. 계절 영향을 빼고 성장했는지 볼 때 써요.' },
  { label: '분기', words: ['분기'], desc: '1년을 3개월씩 나눈 기간이에요. 회사는 분기마다 실적을 발표해요.' },
  { label: '공시', words: ['공시'], desc: '회사가 투자자에게 알려야 하는 중요한 내용을 금융감독원 DART에 공식으로 올린 보고서예요.' },
  { label: '컨센서스', words: ['컨센서스', '시장 기대치', '시장 예상치'], desc: '증권사 애널리스트들이 예상한 실적의 평균이에요. 실제 실적이 이보다 좋으면 "서프라이즈"라고 해요.' },
  { label: '가이던스', words: ['가이던스'], desc: '회사가 직접 밝힌 앞으로의 실적 전망이에요.' },
  { label: '턴어라운드', words: ['턴어라운드', '흑자 전환'], desc: '적자이던 회사가 이익을 내는 상태로 돌아서는 것이에요.' },
  { label: '업황', words: ['업황', '업종 사이클', '사이클'], desc: '회사가 속한 산업 전체의 경기예요. 반도체처럼 좋고 나쁨이 주기적으로 반복되는 업종이 많아요.' },
  { label: '수급', words: ['수급', '외국인 순매수', '기관 순매수', '순매수', '순매도'], desc: '누가 주식을 사고 누가 파는지예요. 외국인이나 기관이 계속 사면 주가에 힘이 실린다고 봐요.' },
  { label: '배당', words: ['배당수익률', '배당'], desc: '회사가 번 이익의 일부를 주주에게 나눠주는 돈이에요.' },
  { label: '리스크', words: ['리스크'], desc: '예상과 다르게 손해를 볼 가능성이에요.' },
  { label: '연결 기준', words: ['연결 기준', '연결재무제표'], desc: '자회사 실적까지 합쳐서 계산한 재무제표예요.' },
]

const ASCII = /^[A-Za-z%]/

/** 본문에서 용어를 찾는 정규식. 영문 약어는 단어 경계를 지킨다 (PERFORMANCE 속 PER은 무시). */
const TERM_INDEX = new Map(TERMS.flatMap((t) => t.words.map((w) => [w, t] as const)))
const TERM_RE = new RegExp(
  [...TERM_INDEX.keys()]
    .sort((a, b) => b.length - a.length)
    .map((w) => {
      const e = w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      return ASCII.test(w) ? `(?<![A-Za-z])${e}(?![A-Za-z])` : e
    })
    .join('|'),
  'g',
)

export type TermPiece = string | { text: string; term: Term }

/** 본문을 일반 글자와 용어로 나눈다. 같은 용어는 처음 한 번만 표시해 밑줄이 너무 많아지지 않게 한다. */
export function splitTerms(text: string): TermPiece[] {
  const out: TermPiece[] = []
  const seen = new Set<Term>()
  let last = 0
  for (const m of text.matchAll(TERM_RE)) {
    const term = TERM_INDEX.get(m[0])!
    if (seen.has(term)) continue
    seen.add(term)
    if (m.index > last) out.push(text.slice(last, m.index))
    out.push({ text: m[0], term })
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}
