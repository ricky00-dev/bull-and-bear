/**
 * 앱 아이콘 만들기: 캐릭터 그림(src/components/Mascot.tsx)에서 SVG·PNG를 뽑는다.
 * 그림을 고치면 다시 실행: npx tsx --tsconfig scripts/tsconfig.json scripts/icons.tsx
 */
import { writeFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import sharp from 'sharp'
import { MascotArt } from '../src/components/Mascot'

const BG = '#111318'

/** maskable은 가장자리를 잘라 내므로 배경을 꽉 채우고 그림을 안쪽 70%에 둔다 */
function icon({ rounded, scale }: { rounded: boolean; scale: number }) {
  const w = 154 * scale
  const h = 96 * scale
  return renderToStaticMarkup(
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
      <rect width="512" height="512" rx={rounded ? 112 : 0} fill={BG} />
      <g transform={`translate(${(512 - w) / 2} ${(512 - h) / 2 + 8 * scale}) scale(${scale})`}>
        <MascotArt side="bull" facing={1} />
        <g transform="translate(58 0)">
          <MascotArt side="bear" facing={-1} />
        </g>
      </g>
    </svg>,
  )
}

const any = icon({ rounded: true, scale: 2.55 })
const maskable = icon({ rounded: false, scale: 2.05 })
writeFileSync('public/icon.svg', any + '\n')
await sharp(Buffer.from(any)).resize(192).png().toFile('public/icon-192.png')
await sharp(Buffer.from(any)).resize(512).png().toFile('public/icon-512.png')
await sharp(Buffer.from(maskable)).resize(512).png().toFile('public/icon-maskable-512.png')
// iOS 홈 화면은 SVG를 못 쓰고 모서리를 알아서 깎는다
await sharp(Buffer.from(maskable)).resize(180).png().toFile('public/apple-touch-icon.png')
console.log('icons written')
