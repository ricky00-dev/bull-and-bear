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
      registerType: 'autoUpdate',
      manifest: {
        name: '불앤베어',
        short_name: '불앤베어',
        description: 'AI 토론을 보고 먼저 판정하는 모의투자 학습',
        lang: 'ko',
        theme_color: '#F4F5F7',
        background_color: '#F4F5F7',
        display: 'standalone',
        start_url: '/',
        icons: [{ src: '/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' }],
      },
    }),
  ],
})
