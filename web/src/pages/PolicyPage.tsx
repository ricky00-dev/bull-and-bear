import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { Screen, TopBar } from '../components/ui'

/** 문의처. 팀 메일이 정해지면 여기만 바꾼다 */
export const CONTACT = '졸업 전시 부스에서 팀원에게 물어봐 주세요. 내 기록은 마이 > 내 기록 모두 삭제에서 바로 지울 수 있어요.'
const EFFECTIVE = '2026년 11월 4일'

/**
 * 개인정보 처리방침과 이용약관. 실제로 저장하는 것만 적는다.
 * 저장 항목을 바꾸면(카카오 로그인 등) 이 문서도 같이 고친다.
 */
export function PolicyPage() {
  const { kind } = useParams()
  const terms = kind === 'terms'
  return (
    <Screen>
      <TopBar title={terms ? '이용약관' : '개인정보 처리방침'} sub={`${EFFECTIVE}부터`} back="/my" />
      <div className="flex gap-2 px-5 pb-3">
        <Tab to="/policy/privacy" on={!terms}>
          개인정보 처리방침
        </Tab>
        <Tab to="/policy/terms" on={terms}>
          이용약관
        </Tab>
      </div>
      <main className="flex flex-1 flex-col gap-5 px-5 pb-10 text-[14px] leading-relaxed">{terms ? <Terms /> : <Privacy />}</main>
    </Screen>
  )
}

function Privacy() {
  return (
    <>
      <p className="text-sub">
        불앤베어(이하 "서비스")는 졸업 전시를 위해 만든 교육용 모의 서비스예요. 이름, 전화번호, 이메일 같은 개인 식별 정보는 받지
        않고, 서비스를 쓰는 데 꼭 필요한 기록만 저장해요.
      </p>
      <Section title="1. 저장하는 정보">
        <ul className="list-disc pl-5">
          <li>게스트 식별값: 처음 접속할 때 무작위로 만든 접근 토큰. 서버에는 토큰을 변환한 값(해시)만 저장해요.</li>
          <li>
            카카오로 시작한 경우: 카카오 회원번호만 저장해요. 이름, 이메일, 프로필 사진 같은 동의 항목은 받지 않고, 카카오
            로그인에 쓰인 카카오 토큰도 저장하지 않아요.
          </li>
          <li>직접 입력한 것: 판정(매수·보류·매도), 확신도, 고른 근거, 한 줄 메모, 닉네임</li>
          <li>퀴즈 기록: 푼 문제, 고른 답, 맞힘 여부</li>
          <li>이용 시각: 판정·퀴즈를 낸 시각</li>
        </ul>
        <p>접속 IP나 기기 정보는 따로 저장하지 않아요. 쿠키도 쓰지 않아요.</p>
      </Section>
      <Section title="2. 쓰는 목적">
        <ul className="list-disc pl-5">
          <li>내 판정을 3·7거래일 뒤 실제 주가로 채점하고 기록을 보여주기 위해</li>
          <li>퀴즈 점수와 랭킹을 보여주기 위해 (랭킹에는 닉네임 또는 "게스트 #번호"·"회원 #번호"만 보여요)</li>
          <li>개인을 알아볼 수 없게 합친 통계(예: 판정 분포, 사람 vs AI 적중률)를 전시에서 보여주기 위해</li>
        </ul>
      </Section>
      <Section title="3. 보관 기간과 삭제">
        <p>
          졸업 전시가 끝나고 서비스를 닫을 때 모두 지워요. 그 전에도 <b>마이 → 내 기록 모두 삭제</b>를 누르면 판정, 메모, 퀴즈
          기록, 닉네임, 카카오 회원번호가 바로 지워져요. AI 토론 내용은 다른 사람도 보는 공용 기록이라 남지만, 누가 요청했는지는 지워요.
        </p>
      </Section>
      <Section title="4. 브라우저에 저장하는 것">
        <p>
          접근 토큰, 최근 검색어, 소개 화면을 봤는지 여부를 이 기기 브라우저에만 저장해요. 브라우저 데이터를 지우면 이 기기의
          기록과 연결이 끊겨요.
        </p>
      </Section>
      <Section title="5. 다른 곳에 맡기거나 주는 정보">
        <ul className="list-disc pl-5">
          <li>카카오 로그인: 로그인할 때 카카오(주식회사 카카오)에서 회원번호를 받아요. 카카오에 보내는 정보는 없어요.</li>
          <li>서버: Amazon Web Services 서울 리전에서 운영해요.</li>
          <li>
            AI 토론: 주가·재무·공시·뉴스 같은 공개 자료만 AI(Anthropic Claude)에 보내요. 내 판정, 메모, 닉네임은 AI에 보내지
            않아요.
          </li>
        </ul>
        <p>위 외에 제3자에게 제공하지 않아요.</p>
      </Section>
      <Section title="6. 문의">
        <p>{CONTACT}</p>
      </Section>
    </>
  )
}

function Terms() {
  return (
    <>
      <Section title="1. 서비스 성격">
        <p>
          불앤베어는 AI 토론을 보고 투자 근거를 읽는 연습을 하는 교육용 모의 서비스예요. 실제 돈이 오가지 않고, 주식을 사고팔 수
          없어요.
        </p>
      </Section>
      <Section title="2. 투자 권유가 아니에요">
        <p>
          AI 토론과 판정, 채점 결과는 학습용 자료예요. 특정 종목을 사거나 팔라는 권유가 아니고, 정확성을 보장하지 않아요. 실제 투자
          판단과 그 결과는 본인 책임이에요.
        </p>
      </Section>
      <Section title="3. 데이터의 한계">
        <p>
          주가와 재무 자료는 공개 출처에서 받아오며 늦거나 틀릴 수 있어요. AI는 자료를 잘못 해석하거나 숫자를 틀리게 옮길 수 있어요.
          근거 칩을 눌러 원자료를 함께 확인해 주세요.
        </p>
      </Section>
      <Section title="4. 이용 규칙">
        <ul className="list-disc pl-5">
          <li>다른 사람을 불쾌하게 하거나 사칭하는 닉네임은 쓸 수 없고, 운영자가 바꾸거나 지울 수 있어요.</li>
          <li>자동화 도구로 토론을 대량 요청하는 등 서비스 운영을 방해하면 이용을 막을 수 있어요.</li>
          <li>AI 비용 때문에 하루 토론 요청 횟수에 제한이 있어요.</li>
        </ul>
      </Section>
      <Section title="5. 서비스 종료">
        <p>졸업 전시용 프로젝트라 전시가 끝난 뒤 예고 후 종료할 수 있어요. 종료할 때 저장된 기록은 모두 지워요.</p>
      </Section>
      <Section title="6. 문의">
        <p>{CONTACT}</p>
      </Section>
      <p className="text-xs text-sub">
        개인정보 처리는 <Link to="/policy/privacy" className="font-bold underline">개인정보 처리방침</Link>을 따라요.
      </p>
    </>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h2 className="text-[15px] font-extrabold">{title}</h2>
      {children}
    </section>
  )
}

function Tab({ to, on, children }: { to: string; on: boolean; children: ReactNode }) {
  return (
    <Link
      to={to}
      replace
      aria-current={on ? 'page' : undefined}
      className={`flex min-h-10 items-center rounded-xl px-3.5 text-[13px] font-bold ${on ? 'bg-point text-on-point' : 'bg-surface-2 text-sub'}`}
    >
      {children}
    </Link>
  )
}
