import { useEffect, useState } from 'react'
import { useRegisterSW } from 'virtual:pwa-register/react'

/** 입력 중 자동 새로고침을 피하고 사용자 동작으로 업데이트한다. */
export function AppUpdateNotice() {
  const [registration, setRegistration] = useState<ServiceWorkerRegistration>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const {needRefresh:[needRefresh], updateServiceWorker} = useRegisterSW({immediate:true, onRegisteredSW:(_url,r)=>setRegistration(r)})
  useEffect(() => {
    if (!registration) return
    const check = () => {if (navigator.onLine && !document.hidden) registration.update().catch(()=>{})}
    window.addEventListener('focus',check)
    document.addEventListener('visibilitychange',check)
    const timer = window.setInterval(check,60_000)
    return () => {window.removeEventListener('focus',check);document.removeEventListener('visibilitychange',check);window.clearInterval(timer)}
  },[registration])
  async function update() {
    setBusy(true)
    setError(false)
    try { await updateServiceWorker(true) } catch { setError(true) } finally { setBusy(false) }
  }
  if (!needRefresh) return null
  return <aside aria-label="앱 업데이트" className="mx-auto flex max-w-[960px] flex-wrap items-center justify-between gap-2 bg-white px-5 py-3 text-sm" role="status">
    <span>{error ? '업데이트하지 못했어요. 다시 시도해 주세요.' : '새 버전이 준비됐어요.'}</span>
    <button type="button" disabled={busy} onClick={update} className="pressable min-h-touch rounded-control border border-line px-3 font-bold disabled:opacity-50">{busy ? '업데이트 중…' : '새 화면으로 업데이트'}</button>
  </aside>
}
