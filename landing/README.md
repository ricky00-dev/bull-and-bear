# 불앤베어 랜딩

서비스 소개 페이지 (Next.js 16, Tailwind 4). 앱 본체는 `web/`이고 EC2에서 돌아간다. 여기서는 "바로 체험" 버튼으로 앱에 연결만 한다.

```bash
npm install
npm run dev      # http://localhost:3000
npm run build
```

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `NEXT_PUBLIC_APP_URL` | `https://54-253-242-203.sslip.io` | "바로 체험"·QR이 여는 앱 주소 |

Vercel: 프로젝트 Root Directory를 `landing`으로 잡으면 된다. 캐릭터 이미지는 `web/src/assets/characters`에서 복사해 왔다.
