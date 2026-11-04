import { Route, Routes, useLocation } from 'react-router'
import { ScrollPosition } from './components/ScrollPosition'
import { AppUpdateNotice } from './components/AppUpdateNotice'
import { DebatePage } from './pages/DebatePage'
import { ExhibitPage } from './pages/ExhibitPage'
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

export default function App() {
  // 전시 화면은 메뉴 없이 한 화면 전체를 쓴다
  const exhibit = useLocation().pathname === '/exhibit'
  return (
    <div className="flex min-h-full">
      <ScrollPosition />
      {!exhibit && <SideNav />}
      <div className="flex min-h-full min-w-0 flex-1 flex-col">
        <AppUpdateNotice />
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
          <Route path="/exhibit" element={<ExhibitPage />} />
          <Route path="*" element={<HomePage />} />
        </Routes>
      </div>
    </div>
  )
}
