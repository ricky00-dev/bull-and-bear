import type { Metadata, Viewport } from "next";
import { Noto_Sans_KR } from "next/font/google";
import "./globals.css";

// 한글 글꼴은 subset 목록이 없어 미리 불러오기를 끈다
const noto = Noto_Sans_KR({
  variable: "--font-noto",
  weight: ["500", "700", "900"],
  preload: false,
});

// 공유 미리보기 이미지의 절대 주소. Vercel은 운영 도메인을 이 환경 변수로 넣어 준다
const site = process.env.VERCEL_PROJECT_PRODUCTION_URL;

export const metadata: Metadata = {
  metadataBase: new URL(site ? `https://${site}` : "http://localhost:3000"),
  title: "불앤베어, 같은 자료로 다른 결론을 읽는 연습",
  description:
    "매수 AI와 매도 AI가 같은 자료로 토론하고, 내가 먼저 판단한 뒤 실제 주가로 나와 AI를 함께 채점받는 투자 판단 연습 서비스.",
  openGraph: {
    title: "불앤베어",
    description: "같은 자료, 다른 결론. 판단은 내가.",
    images: ["/characters/bull.png"],
  },
};

export const viewport: Viewport = {
  themeColor: "#0b0c0e",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className={`${noto.variable} antialiased`}>
      <body className="min-h-dvh font-sans">{children}</body>
    </html>
  );
}
