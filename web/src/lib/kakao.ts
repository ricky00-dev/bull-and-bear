/** 카카오 로그인 (인가 코드 방식). 카카오 앱에 이 주소를 Redirect URI로 등록해야 한다: <사이트 주소>/auth/kakao */
export const KAKAO_CALLBACK_PATH = '/auth/kakao'

const STATE_KEY = 'bb.kakao.state'
const RETURN_KEY = 'bb.kakao.return'

export function kakaoRedirectUri() {
  return `${window.location.origin}${KAKAO_CALLBACK_PATH}`
}

/** 카카오 동의 화면으로 보낸다. 돌아오면 원래 보던 화면으로 되돌린다 */
export function startKakaoLogin(clientId: string) {
  const state = crypto.randomUUID()
  try {
    sessionStorage.setItem(STATE_KEY, state)
    sessionStorage.setItem(RETURN_KEY, window.location.pathname)
  } catch {
    // 저장소를 못 쓰면 돌아와서 state 확인에 실패하고 다시 시도하라고 안내한다
  }
  const params = new URLSearchParams({ client_id: clientId, redirect_uri: kakaoRedirectUri(), response_type: 'code', state })
  window.location.assign(`https://kauth.kakao.com/oauth/authorize?${params}`)
}

/** 돌아온 state가 보낸 것과 같은지 (다른 사이트가 로그인을 꾸며 보내는 것을 막는다). 읽기만 해서 여러 번 불러도 같다 */
export function checkKakaoState(state: string | null): { ok: boolean; returnTo: string } {
  let saved: string | null = null
  let returnTo = '/my'
  try {
    saved = sessionStorage.getItem(STATE_KEY)
    returnTo = sessionStorage.getItem(RETURN_KEY) ?? returnTo
  } catch {
    // 저장소를 못 쓰면 확인할 수 없다
  }
  if (returnTo === KAKAO_CALLBACK_PATH) returnTo = '/my'
  return { ok: !!state && state === saved, returnTo }
}

export function clearKakaoState() {
  try {
    sessionStorage.removeItem(STATE_KEY)
    sessionStorage.removeItem(RETURN_KEY)
  } catch {
    // 지울 것도 없다
  }
}
