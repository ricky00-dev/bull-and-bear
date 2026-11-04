import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { KakaoButton } from '../components/KakaoButton'
import { Card, Screen, TopBar } from '../components/ui'
import { api, ApiError, setToken } from '../lib/api'
import { checkKakaoState, clearKakaoState, kakaoRedirectUri } from '../lib/kakao'

/** 카카오 동의 화면에서 돌아오는 곳. 인가 코드를 서버에 넘기고, 받은 토큰으로 바꾼 뒤 원래 화면으로 */
export function KakaoCallbackPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [check] = useState(() => checkKakaoState(params.get('state')))
  const [failed, setFailed] = useState<string | null>(null)
  const started = useRef(false)
  const code = params.get('code')
  const cancelled = !!params.get('error') // 동의 화면에서 취소
  const error = failed ?? (!cancelled && (!check.ok || !code) ? '로그인 요청을 확인하지 못했어요. 다시 시도해 주세요.' : null)

  useEffect(() => {
    if (started.current) return // 개발 모드의 두 번 실행 방지. 인가 코드는 한 번만 쓸 수 있다
    started.current = true
    if (cancelled) {
      clearKakaoState()
      navigate(check.returnTo, { replace: true })
      return
    }
    if (!check.ok || !code) return
    clearKakaoState()
    api
      .kakaoLogin(code, kakaoRedirectUri())
      .then((res) => {
        setToken(res.token)
        queryClient.clear()
        navigate(check.returnTo, { replace: true })
      })
      .catch((e: unknown) => setFailed(e instanceof ApiError ? e.message : '카카오 로그인을 다시 시도해 주세요'))
  }, [cancelled, check, code, navigate, queryClient])

  return (
    <Screen>
      <TopBar title="카카오 로그인" back="/my" />
      <main className="flex flex-1 flex-col gap-3.5 px-5 pb-6">
        {error ? (
          <Card className="flex flex-col gap-3">
            <p className="text-[15px] font-extrabold">{error}</p>
            <p className="text-[13px] text-sub">지금까지의 기록은 그대로 있어요.</p>
            <KakaoButton className="text-[15px]" />
          </Card>
        ) : (
          <p className="py-16 text-center text-[15px] font-bold text-sub">로그인하는 중이에요…</p>
        )}
      </main>
    </Screen>
  )
}
