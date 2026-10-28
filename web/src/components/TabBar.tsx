import { NavLink } from 'react-router'
import { Icon } from './ui'

const TABS = [
  { to: '/', label: '홈', icon: 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z', ready: true },
  { to: '/quiz', label: '퀴즈', icon: 'M3 12a9 9 0 1 0 3-6.7M3 4v4h4M12 7v5l3 2', ready: true },
  { to: '/me', label: '내 판정', icon: 'M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9', ready: true },
  { to: '/my', label: '마이', icon: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0', ready: false },
]

/** 하단 탭. 마이는 아직 준비 중이라 눌리지 않는다. */
export function TabBar() {
  return (
    <nav aria-label="주 메뉴" className="pb-safe sticky bottom-0 z-10 grid grid-cols-4 border-t border-line bg-white px-2 pt-1.5">
      {TABS.map((t) =>
        t.ready ? (
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
        ) : (
          <span key={t.to} aria-disabled="true" className="flex min-h-13 flex-col items-center justify-center gap-0.5 text-[11px] font-bold text-line">
            <Icon d={t.icon} size={22} />
            {t.label}
          </span>
        ),
      )}
    </nav>
  )
}
