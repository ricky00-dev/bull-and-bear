import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { startKakaoLogin } from '../lib/kakao'

/** 카카오로 시작. 서버에 카카오 키가 없으면 "준비 중"으로 막아 둔다 */
export function KakaoButton({ className = '' }: { className?: string }) {
  const config = useQuery({ queryKey: ['kakao-config'], queryFn: api.kakaoConfig, staleTime: Infinity })
  const clientId = config.data?.enabled ? config.data.clientId : null
  return (
    <button
      type="button"
      disabled={!clientId}
      onClick={() => clientId && startKakaoLogin(clientId)}
      className={`pressable flex min-h-12 items-center justify-center gap-2 rounded-xl bg-[#fee500] font-extrabold text-[#191600] disabled:opacity-60 ${className}`}
    >
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <path fill="currentColor" d="M12 3C6.48 3 2 6.48 2 10.77c0 2.77 1.86 5.2 4.66 6.57l-.95 3.48c-.08.3.26.54.52.37l4.15-2.74c.53.06 1.07.1 1.62.1 5.52 0 10-3.48 10-7.78S17.52 3 12 3z" />
      </svg>
      {config.isPending ? '카카오로 시작' : clientId ? '카카오로 시작' : '카카오로 시작 (준비 중)'}
    </button>
  )
}
