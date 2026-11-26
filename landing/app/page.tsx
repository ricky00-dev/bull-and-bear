import Image from "next/image";
import { AppQr } from "./qr";
import { Reveal } from "./reveal";

const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? "https://54-253-242-203.sslip.io";

export default function Home() {
  return (
    <main className="overflow-x-clip">
      <Header />
      <Hero />
      <DebateScene />
      <Steps />
      <Scoring />
      <Quiz />
      <Closing />
      <Footer />
    </main>
  );
}

function Header() {
  return (
    <header className="absolute inset-x-0 top-0 z-20">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
        <a href="#" className="flex items-center gap-2.5 font-black tracking-tight">
          <Image src="/logo-mark.png" alt="" width={32} height={32} className="rounded-lg" />
          불앤베어
        </a>
        <a
          href={APP_URL}
          className="rounded-full border border-line bg-surface/80 px-4 py-2 text-sm font-bold backdrop-blur transition hover:border-point hover:text-point"
        >
          바로 체험
        </a>
      </div>
    </header>
  );
}

/* ── 히어로 ─────────────────────────────────────────── */

function Hero() {
  return (
    <section className="hero relative flex min-h-[100svh] flex-col items-center justify-center px-5 pb-56 pt-28 text-center sm:pb-40">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_50%_at_50%_35%,rgb(255_138_61/0.10),transparent_70%)]"
      />
      <HeroChart />
      {/* 글자 뒤로 지나가는 선을 눌러 제목이 먼저 읽히게 한다 */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(38%_30%_at_50%_40%,rgb(11_12_14/0.85)_35%,transparent_100%)]"
      />

      <div className="relative z-10 flex max-w-3xl flex-col items-center">
        <p className="fade-up text-sm font-bold text-point" style={{ animationDelay: "0.1s" }}>
          AI 토론으로 연습하는 투자 판단
        </p>
        <h1
          className="fade-up mt-4 text-[2.6rem] font-black leading-[1.15] tracking-tight sm:text-7xl"
          style={{ animationDelay: "0.25s" }}
        >
          같은 자료,<br className="sm:hidden" /> <span className="text-up-ink">다른</span> <span className="text-down-ink">결론</span>.
          <br />
          판단은 <span className="text-point">내가</span>.
        </h1>
        <p className="fade-up mt-6 max-w-xl text-base leading-relaxed text-sub sm:text-lg" style={{ animationDelay: "0.45s" }}>
          매수 AI와 매도 AI가 같은 자료로 토론해요. 근거를 골라 먼저 판단하면,
          3·7거래일 뒤 실제 주가로 나와 AI를 함께 채점해요.
        </p>

        <div className="fade-up mt-9 flex flex-col items-center gap-5 sm:flex-row" style={{ animationDelay: "0.65s" }}>
          <a
            href={APP_URL}
            className="group flex items-center gap-2 rounded-full bg-point px-7 py-4 text-base font-black text-on-point shadow-[0_10px_40px_-10px_rgb(255_138_61/0.7)] transition hover:brightness-110"
          >
            지금 토론 보러 가기
            <span className="transition group-hover:translate-x-1">→</span>
          </a>
          <div className="hidden items-center gap-3 text-left sm:flex">
            <AppQr url={APP_URL} />
            <p className="text-sm leading-snug text-sub">
              휴대폰으로
              <br />
              바로 열기
            </p>
          </div>
        </div>
        <p className="fade-up mt-5 text-xs text-faint" style={{ animationDelay: "0.8s" }}>
          설치 없이 게스트로 바로 시작 · 투자 권유가 아닌 교육용 서비스
        </p>
      </div>

      {/* 캐릭터에 마우스를 올리거나 탭하면 그 편 그래프가 살아난다 (globals.css의 .hero:has) */}
      <div tabIndex={0} className="char char-bull float-a absolute bottom-0 left-[2%] z-10 outline-none sm:left-[6%]">
        <span className="char-badge bg-up text-white">▲ 오를 거예요</span>
        <Image
          src="/characters/bull.png"
          alt="매수 AI 황소"
          width={276}
          height={360}
          preload
          className="char-img h-44 w-auto drop-shadow-[0_20px_40px_rgb(229_56_59/0.35)] sm:h-80"
        />
      </div>
      <div tabIndex={0} className="char char-bear float-b absolute bottom-0 right-[4%] z-10 outline-none sm:right-[8%]">
        <span className="char-badge bg-down text-white">▼ 내릴 거예요</span>
        <Image
          src="/characters/bear.png"
          alt="매도 AI 곰"
          width={179}
          height={360}
          preload
          className="char-img h-44 w-auto drop-shadow-[0_20px_40px_rgb(47_111_235/0.35)] sm:h-80"
        />
      </div>
    </section>
  );
}

/** 같은 출발점에서 빨강(상승)은 위로, 파랑(하락)은 아래로 갈라지는 두 선과 바닥의 캔들 */
function HeroChart() {
  const start = { x: 60, y: 300 };
  const up = walk(start, { x: 1140, y: 70 }, 7);
  const down = walk(start, { x: 1140, y: 500 }, 19);
  const candles = Array.from({ length: 34 }, (_, i) => {
    const r = rand(i * 13 + 5);
    return { x: 30 + i * 35, h: 24 + r * 90, up: rand(i * 7 + 1) > 0.45 };
  });

  return (
    <svg
      aria-hidden
      viewBox="0 0 1200 600"
      preserveAspectRatio="xMidYMid slice"
      className="pointer-events-none absolute inset-0 h-full w-full"
    >
      <defs>
        <linearGradient id="grad-up" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#e5383b" stopOpacity="0.22" />
          <stop offset="1" stopColor="#e5383b" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="grad-down" x1="0" x2="0" y1="1" y2="0">
          <stop offset="0" stopColor="#2f6feb" stopOpacity="0.22" />
          <stop offset="1" stopColor="#2f6feb" stopOpacity="0" />
        </linearGradient>
      </defs>

      {[120, 240, 360, 480].map((y) => (
        <line key={y} x1="0" x2="1200" y1={y} y2={y} stroke="#26282c" strokeDasharray="4 8" />
      ))}

      {(["up", "down"] as const).map((side) => (
        <g key={side} className={`candles candles-${side}`}>
          {candles.map((c, i) =>
            c.up === (side === "up") ? (
              <rect
                key={i}
                className="candle"
                style={{ animationDelay: `${i * 45}ms, ${1500 + i * 120}ms` }}
                x={c.x}
                y={600 - c.h}
                width="16"
                height={c.h}
                rx="3"
                fill={side === "up" ? "#e5383b" : "#2f6feb"}
              />
            ) : null,
          )}
        </g>
      ))}

      <g className="series series-up">
        <path className="area" d={`${toPath(up)} L1140,600 L60,600 Z`} fill="url(#grad-up)" />
        <path className="draw line" pathLength={1} d={toPath(up)} fill="none" stroke="#e5383b" strokeWidth="3" strokeLinejoin="round" />
        <circle className="tip" cx={1140} cy={70} r="7" fill="#ff6b6e" />
      </g>
      <g className="series series-down">
        <path className="area" d={`${toPath(down)} L1140,0 L60,0 Z`} fill="url(#grad-down)" />
        <path className="draw draw-late line" pathLength={1} d={toPath(down)} fill="none" stroke="#2f6feb" strokeWidth="3" strokeLinejoin="round" />
        <circle className="tip" cx={1140} cy={500} r="7" fill="#7aa7ff" />
      </g>

      <circle cx={start.x} cy={start.y} r="6" fill="#f2f2f3" />
    </svg>
  );
}

/* ── 토론 한 장면 ───────────────────────────────────── */

function DebateScene() {
  return (
    <section className="mx-auto max-w-6xl px-5 py-24 sm:py-32">
      <SectionTitle kicker="실제 토론 한 장면 · 삼성전자" title="같은 숫자를 보고도 결론이 갈려요" />
      <Reveal className="mx-auto mt-14 flex max-w-2xl flex-col gap-5">
        <Bubble
          side="bull"
          style={{ "--i": 0 } as React.CSSProperties}
          name="매수 AI"
          text="PER이 7.72배예요. 벌어들이는 이익에 비해 주가가 싼 구간이라고 봐요."
          chip="PER · 재무제표 기준"
        />
        <Bubble
          side="bear"
          style={{ "--i": 1 } as React.CSSProperties}
          name="매도 AI"
          text="한 달 수익률이 −20.6%예요. 싸 보이는 건 주가가 먼저 빠졌기 때문일 수 있어요. 추가 하락을 경계해야 해요."
          chip="1개월 수익률 · 시세 기준"
        />
        <div style={{ "--i": 2 } as React.CSSProperties} className="flex items-center gap-3 self-center rounded-2xl border border-line bg-mod-soft px-4 py-3">
          <Image src="/characters/owl-face.png" alt="" width={36} height={36} className="rounded-full" />
          <p className="text-sm text-sub">
            <b className="text-ink">중재자 AI의 판정은 봉인돼 있어요.</b> 내가 먼저 판단해야 열려요.
          </p>
          <span aria-hidden className="text-lg">🔒</span>
        </div>
      </Reveal>
    </section>
  );
}

function Bubble({
  side,
  name,
  text,
  chip,
  style,
}: {
  side: "bull" | "bear";
  name: string;
  text: string;
  chip: string;
  style?: React.CSSProperties;
}) {
  const bull = side === "bull";
  return (
    <div style={style} className={`flex items-end gap-3 ${bull ? "" : "flex-row-reverse"}`}>
      <Image
        src={bull ? "/characters/bull-face.png" : "/characters/bear-face.png"}
        alt=""
        width={48}
        height={48}
        className={`shrink-0 rounded-full ring-2 ${bull ? "ring-up/60" : "ring-down/60"}`}
      />
      <div
        className={`max-w-[85%] rounded-3xl border px-5 py-4 ${
          bull ? "rounded-bl-md border-up/30 bg-up-soft" : "rounded-br-md border-down/30 bg-down-soft"
        }`}
      >
        <p className={`text-xs font-bold ${bull ? "text-up-ink" : "text-down-ink"}`}>{name}</p>
        <p className="mt-1.5 leading-relaxed">{text}</p>
        <span className="mt-3 inline-flex items-center gap-1 rounded-lg bg-black/30 px-2.5 py-1 text-xs text-sub">
          <span aria-hidden>🔎</span> 근거: {chip}
        </span>
      </div>
    </div>
  );
}

/* ── 세 번 직접 판단 ─────────────────────────────────── */

const STEPS = [
  {
    no: "01",
    title: "근거를 고른다",
    body: "발언마다 붙은 근거를 눌러 출처와 기준일을 확인하고, 설득력 있는 근거를 직접 골라요.",
    face: "/characters/bull-face.png",
  },
  {
    no: "02",
    title: "먼저 판단한다",
    body: "매수·보류·매도 중 하나를 내가 먼저 정해요. 그 전까지 AI의 결론은 보이지 않아요.",
    face: "/characters/bear-face.png",
  },
  {
    no: "03",
    title: "결과로 복기한다",
    body: "3·7거래일 뒤 실제 주가로 나와 AI가 같은 기준으로 채점돼요. 어떤 근거가 맞았는지 돌아봐요.",
    face: "/characters/owl-face.png",
  },
];

function Steps() {
  return (
    <section className="border-y border-line bg-surface/40">
      <div className="mx-auto max-w-6xl px-5 py-24 sm:py-32">
        <SectionTitle kicker="불앤베어가 연습시키는 것" title="정답을 주지 않고, 세 번 직접 판단하게 해요" />
        <Reveal className="mt-14 grid gap-5 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <div
              key={s.no}
              style={{ "--i": i } as React.CSSProperties}
              className="rounded-3xl border border-line bg-surface p-7 transition hover:-translate-y-1 hover:border-point/50"
            >
              <Image src={s.face} alt="" width={52} height={52} className="rounded-2xl" />
              <p className="mt-6 text-sm font-bold text-faint">{s.no}</p>
              <h3 className="mt-1 text-2xl font-black">{s.title}</h3>
              <p className="mt-3 leading-relaxed text-sub">{s.body}</p>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

/* ── 채점 방식 ──────────────────────────────────────── */

function Scoring() {
  // 판정일(왼쪽 끝) 대비 수익률. 회색 띠가 코스피 ±2%p
  const kospi = "M20,150 C80,146 140,140 200,138 S320,128 380,124";
  const band = "M20,126 C80,122 140,116 200,114 S320,104 380,100 L380,148 C320,152 260,160 200,162 S80,170 20,174 Z";
  const stock = "M20,150 C70,160 110,130 160,118 S260,70 300,76 S360,52 380,46";

  return (
    <section className="mx-auto grid max-w-6xl items-center gap-14 px-5 py-24 sm:py-32 md:grid-cols-2">
      <div>
        <SectionTitle align="left" kicker="채점 기준" title="시장보다 잘했는지로 채점해요" />
        <p className="mt-5 leading-relaxed text-sub">
          시장 전체가 오르면 대부분의 종목이 같이 올라요. 그래서 종목 수익률에서 코스피 수익률을 뺀
          <b className="text-ink"> 초과수익</b>으로 채점해요. 시장 분위기가 아니라 그 종목을 읽었는지가 남아요.
        </p>
        <ul className="mt-7 space-y-3">
          <Rule tone="up" label="매수" body="코스피보다 +2%p 넘게 오르면" />
          <Rule tone="mod" label="보류" body="코스피와 ±2%p 안에서 움직이면" />
          <Rule tone="down" label="매도" body="코스피보다 −2%p 넘게 내리면" />
        </ul>
      </div>

      <Reveal className="rounded-3xl border border-line bg-surface p-6">
        <div>
          <div className="flex items-center justify-between text-xs text-faint">
            <span>판정일</span>
            <span>7거래일 뒤</span>
          </div>
          <svg viewBox="0 0 400 200" className="mt-3 w-full" role="img" aria-label="종목 수익률이 코스피 ±2%p 띠 위로 올라가 매수가 정답인 예시">
            <path d={band} fill="#ffffff" opacity="0.06" />
            <path className="draw-on-reveal" pathLength={1} d={kospi} fill="none" stroke="#6b6f77" strokeWidth="2" />
            <path className="draw-on-reveal" pathLength={1} d={stock} fill="none" stroke="#e5383b" strokeWidth="3" strokeLinecap="round" />
            <circle cx="380" cy="46" r="5" fill="#ff6b6e" />
          </svg>
          <div className="mt-3 flex flex-wrap gap-4 text-xs text-sub">
            <Legend className="bg-up" label="종목" />
            <Legend className="bg-faint" label="코스피" />
            <Legend className="bg-white/10" label="보류 구간 (±2%p)" />
          </div>
        </div>
        <p style={{ "--i": 1 } as React.CSSProperties} className="mt-5 rounded-2xl bg-up-soft px-4 py-3 text-sm">
          띠 위로 벗어났으니 <b className="text-up-ink">매수가 정답</b>. 나와 AI가 같은 기준으로 채점돼요.
        </p>
      </Reveal>
    </section>
  );
}

function Rule({ tone, label, body }: { tone: "up" | "down" | "mod"; label: string; body: string }) {
  const color = { up: "bg-up-soft text-up-ink", down: "bg-down-soft text-down-ink", mod: "bg-mod-soft text-mod" }[tone];
  return (
    <li className="flex items-center gap-3">
      <span className={`w-14 rounded-lg py-1 text-center text-sm font-black ${color}`}>{label}</span>
      <span className="text-sub">{body}</span>
    </li>
  );
}

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-2 w-4 rounded-sm ${className}`} />
      {label}
    </span>
  );
}

/* ── 타임머신 퀴즈 ───────────────────────────────────── */

function Quiz() {
  return (
    <section className="border-y border-line bg-surface/40">
      <div className="mx-auto grid max-w-6xl items-center gap-14 px-5 py-24 sm:py-32 md:grid-cols-2">
        <Reveal className="order-2 mx-auto w-full max-w-sm md:order-1">
          <div className="rounded-3xl border border-line bg-surface p-6 shadow-2xl">
            <div className="flex items-center justify-between text-xs text-faint">
              <span>타임머신 퀴즈 3 / 5</span>
              <span>○월 ○일</span>
            </div>
            <p className="mt-4 text-lg font-black">이 회사, 7거래일 뒤 코스피보다 잘했을까요?</p>
            <div className="mt-4 space-y-2 text-sm text-sub">
              <p className="rounded-xl bg-surface-2 px-3 py-2">
                <b className="text-up-ink">매수 AI</b> · 이 회사는 이익 대비 주가가 낮아요…
              </p>
              <p className="rounded-xl bg-surface-2 px-3 py-2">
                <b className="text-down-ink">매도 AI</b> · 최근 ○○원까지 밀리며 추세가…
              </p>
            </div>
            <div className="mt-5 grid grid-cols-3 gap-2 text-sm font-bold">
              <span className="rounded-xl bg-up-soft py-3 text-center text-up-ink">매수</span>
              <span className="rounded-xl bg-mod-soft py-3 text-center text-mod">보류</span>
              <span className="rounded-xl bg-down-soft py-3 text-center text-down-ink">매도</span>
            </div>
          </div>
        </Reveal>
        <div className="order-1 md:order-2">
          <SectionTitle align="left" kicker="기다리기 힘들다면" title="타임머신 퀴즈로 바로 채점받아요" />
          <p className="mt-5 leading-relaxed text-sub">
            결과가 이미 나온 과거 토론으로 퀴즈를 풀어요. 종목명·날짜·금액처럼 정답을 떠올리게 하는 정보는
            가려서, 이름이 아니라 근거만 보고 판단하게 해요. 답하면 바로 실제 결과를 보여줘요.
          </p>
        </div>
      </div>
    </section>
  );
}

/* ── 마무리 ─────────────────────────────────────────── */

function Closing() {
  return (
    <section className="relative px-5 py-28 text-center sm:py-36">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(50%_60%_at_50%_60%,rgb(255_138_61/0.10),transparent_70%)]"
      />
      <div className="relative mx-auto flex max-w-2xl flex-col items-center">
        <div className="flex -space-x-3">
          <Image src="/characters/bull-face.png" alt="" width={64} height={64} className="rounded-full ring-4 ring-ground" />
          <Image src="/characters/owl-face.png" alt="" width={64} height={64} className="rounded-full ring-4 ring-ground" />
          <Image src="/characters/bear-face.png" alt="" width={64} height={64} className="rounded-full ring-4 ring-ground" />
        </div>
        <h2 className="mt-8 text-3xl font-black leading-tight tracking-tight sm:text-5xl">
          AI가 대신 판단하지 않아요.
          <br />
          <span className="text-point">읽는 눈</span>을 길러 드려요.
        </h2>
        <a
          href={APP_URL}
          className="group mt-10 flex items-center gap-2 rounded-full bg-point px-7 py-4 font-black text-on-point transition hover:brightness-110"
        >
          불앤베어 시작하기
          <span className="transition group-hover:translate-x-1">→</span>
        </a>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-5 py-8 text-xs text-faint sm:flex-row sm:items-center sm:justify-between">
        <span className="flex items-center gap-2 font-bold text-sub">
          <Image src="/logo-mark.png" alt="" width={20} height={20} className="rounded" />
          불앤베어 · 졸업 프로젝트
        </span>
        <span>투자 권유가 아닌 교육용 서비스예요. AI 판정과 채점 결과는 투자 수익을 보장하지 않아요.</span>
      </div>
    </footer>
  );
}

function SectionTitle({ kicker, title, align = "center" }: { kicker: string; title: string; align?: "center" | "left" }) {
  return (
    <div className={align === "center" ? "text-center" : ""}>
      <p className="text-sm font-bold text-point">{kicker}</p>
      <h2 className="mt-3 text-3xl font-black leading-tight tracking-tight sm:text-4xl">{title}</h2>
    </div>
  );
}

/* ── 그래프 계산 ─────────────────────────────────────── */

/** 결정적 의사 난수. 서버·클라이언트에서 같은 그래프가 나오게 한다 */
function rand(seed: number) {
  const x = Math.sin(seed * 9301 + 49297) * 233280;
  return x - Math.floor(x);
}

/** from에서 to까지 흔들리며 가는 꺾은선 */
function walk(from: { x: number; y: number }, to: { x: number; y: number }, seed: number) {
  const n = 26;
  return Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n;
    const wobble = i === 0 || i === n ? 0 : (rand(seed + i) - 0.5) * 70 * Math.sin(Math.PI * t);
    return { x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t + wobble };
  });
}

function toPath(points: { x: number; y: number }[]) {
  return points.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
}
