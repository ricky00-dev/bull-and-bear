import { useEffect } from 'react'
import { Route, Routes, useLocation } from 'react-router'
import { DebatePage } from './pages/DebatePage'
import { HomePage } from './pages/HomePage'
import { JudgePage } from './pages/JudgePage'
import { GlossaryPage } from './pages/GlossaryPage'
import { MyJudgmentsPage } from './pages/MyJudgmentsPage'
import { MyPage } from './pages/MyPage'
import { PolicyPage } from './pages/PolicyPage'
import { QuizHomePage } from './pages/QuizHomePage'
import { QuizPlayPage } from './pages/QuizPlayPage'
import { RankingPage } from './pages/RankingPage'
import { ReportPage } from './pages/ReportPage'
import { RevealPage } from './pages/RevealPage'
import { ScorePage } from './pages/ScorePage'
import { StockPage } from './pages/StockPage'
import { SideNav } from './components/TabBar'

/** 화면이 바뀌면 맨 위에서 시작 (이전 화면의 스크롤 위치가 남지 않게) */
function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}

export default function App() {
  return (
    <div className="flex min-h-full">
      <ScrollToTop />
      <SideNav />
      <div className="flex min-h-full min-w-0 flex-1 flex-col">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/stocks/:ticker" element={<StockPage />} />
          <Route path="/debates/:id" element={<DebatePage />} />
          <Route path="/debates/:id/judge" element={<JudgePage />} />
          <Route path="/debates/:id/reveal" element={<RevealPage />} />
          <Route path="/quiz" element={<QuizHomePage />} />
          <Route path="/quiz/ranking" element={<RankingPage />} />
          <Route path="/quiz/:id" element={<QuizPlayPage />} />
          <Route path="/me" element={<MyJudgmentsPage />} />
          <Route path="/me/judgments/:id" element={<ScorePage />} />
          <Route path="/my" element={<MyPage />} />
          <Route path="/glossary" element={<GlossaryPage />} />
          <Route path="/report" element={<ReportPage />} />
          <Route path="/policy/:kind" element={<PolicyPage />} />
          <Route path="*" element={<HomePage />} />
        </Routes>
      </div>
    </div>
  )
}
