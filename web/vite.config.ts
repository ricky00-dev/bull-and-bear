import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // 홈 화면 설치 + 나중에 웹 푸시(채점 알림). 앱으로 구울 때는 Capacitor가 같은 빌드를 감싼다.
    VitePWA({
      registerType: 'prompt',
      injectRegister: false,
      // API·토론 스트림은 서비스 워커가 건드리지 않는다 (같은 출처로 배포하므로 명시)
      workbox: { navigateFallbackDenylist: [/^\/api\//] },
      manifest: {
        name: '불앤베어',
        short_name: '불앤베어',
        description: 'AI 토론을 보고 먼저 판정하는 모의투자 학습',
        lang: 'ko',
        theme_color: '#0B0C0E',
        background_color: '#0B0C0E',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          // 꽉 찬 그림이라 원형으로 잘리면 바깥 뿔 끝·귀만 잘리고 두 얼굴은 안전 영역 안에 남는다
          { src: '/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
})
