import { useEffect } from 'react'
import { Route, Routes, useLocation } from 'react-router'
import { DebatePage } from './pages/DebatePage'
import { HomePage } from './pages/HomePage'
import { JudgePage } from './pages/JudgePage'
import { RevealPage } from './pages/RevealPage'
import { StockPage } from './pages/StockPage'

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
    <>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/stocks/:ticker" element={<StockPage />} />
        <Route path="/debates/:id" element={<DebatePage />} />
        <Route path="/debates/:id/judge" element={<JudgePage />} />
        <Route path="/debates/:id/reveal" element={<RevealPage />} />
        <Route path="*" element={<HomePage />} />
      </Routes>
    </>
  )
}
