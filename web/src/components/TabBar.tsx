import { NavLink } from 'react-router'
import { Icon } from './ui'

const TABS = [
  { to: '/', label: '홈', icon: 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z' },
  { to: '/quiz', label: '퀴즈', icon: 'M3 12a9 9 0 1 0 3-6.7M3 4v4h4M12 7v5l3 2' },
  { to: '/me', label: '내 판정', icon: 'M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9' },
  { to: '/my', label: '마이', icon: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0' },
]

/** 하단 탭 */
export function TabBar() {
  return (
    <nav aria-label="주 메뉴" className="pb-safe sticky bottom-0 z-10 grid grid-cols-4 border-t border-line bg-white px-2 pt-1.5">
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end
          className={({ isActive }) =>
            `pressable flex min-h-14 flex-col items-center justify-center gap-1 rounded-control text-xs transition-colors ${isActive ? 'font-bold text-ink' : 'font-medium text-sub'}`
          }
        >
          <Icon d={t.icon} size={22} />
          {t.label}
        </NavLink>
      ))}
    </nav>
  )
}
