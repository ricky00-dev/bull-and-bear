import { NavLink } from 'react-router'
import { Icon } from './ui'

const TABS = [
  { to: '/', label: '홈', icon: 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z' },
  { to: '/quiz', label: '퀴즈', icon: 'M3 12a9 9 0 1 0 3-6.7M3 4v4h4M12 7v5l3 2' },
  { to: '/me', label: '내 판정', icon: 'M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9' },
  { to: '/my', label: '마이', icon: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0' },
]

/** 하단 탭. 넓은 화면(md 이상)에서는 숨기고 SideNav가 대신한다 */
export function TabBar() {
  return (
    <nav aria-label="주 메뉴" className="pb-safe sticky bottom-0 z-10 grid grid-cols-4 border-t border-line bg-white px-2 pt-1.5 md:hidden">
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end
          className={({ isActive }) =>
            `flex min-h-13 flex-col items-center justify-center gap-0.5 text-[11px] font-bold ${isActive ? 'text-ink' : 'text-faint'}`
          }
        >
          <Icon d={t.icon} size={22} />
          {t.label}
        </NavLink>
      ))}
    </nav>
  )
}

/** 넓은 화면의 왼쪽 메뉴. 모든 화면에 붙어 있어 상세 화면에서도 바로 이동할 수 있다 */
export function SideNav() {
  return (
    <nav
      aria-label="주 메뉴"
      className="sticky top-0 hidden h-dvh w-56 shrink-0 flex-col gap-1 border-r border-line bg-white px-3 py-6 md:flex lg:w-64"
    >
      <NavLink to="/" className="mb-5 flex items-center gap-2 px-3">
        <span className="flex size-7 items-center justify-center rounded-lg bg-ink text-[13px] font-extrabold text-white">B</span>
        <span className="text-lg font-extrabold tracking-tight">불앤베어</span>
      </NavLink>
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end
          className={({ isActive }) =>
            `flex min-h-12 items-center gap-3 rounded-xl px-3 text-[15px] font-bold ${isActive ? 'bg-ground text-ink' : 'text-sub hover:bg-ground'}`
          }
        >
          <Icon d={t.icon} size={22} />
          {t.label}
        </NavLink>
      ))}
      <p className="mt-auto px-3 text-[11px] leading-relaxed text-faint">교육용 모의 서비스예요. AI 판정은 투자 권유가 아니에요.</p>
    </nav>
  )
}
