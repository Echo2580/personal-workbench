import { CalendarDays, FolderOpen, ListTodo, Settings2, StickyNote } from 'lucide-react'
import type { AppId, Desk } from './useDesk'

const ITEMS: Array<{ id: AppId; label: string; Icon: typeof FolderOpen }> = [
  { id: 'project', label: '项目', Icon: FolderOpen },
  { id: 'todo', label: '待办', Icon: ListTodo },
  { id: 'note', label: '便笺', Icon: StickyNote },
  { id: 'calendar', label: '日历', Icon: CalendarDays },
]

export function Dock({ desk }: { desk: Desk }) {
  const topId = desk.state.zOrder[desk.state.zOrder.length - 1]
  return (
    <nav className="dock" aria-label="应用栏">
      {ITEMS.map(({ id, label, Icon }) => {
        const open = desk.state.windows[id].open
        const active = open && topId === id
        return (
          <button
            key={id}
            className={`dock__item${open ? ' dock__item--open' : ''}${active ? ' dock__item--active' : ''}`}
            onClick={() => desk.dockClick(id)}
            title={label}
            aria-label={label}
            aria-pressed={open}
          >
            <Icon size={19} strokeWidth={1.8} />
            <span className="dock__label">{label}</span>
            {open && (
              <span
                className="dock__dot"
                style={{ background: active ? 'var(--accent)' : 'rgba(236, 230, 214, 0.45)' }}
              />
            )}
          </button>
        )
      })}
      <span className="dock__sep" />
      <button
        className={`dock__item${desk.state.windows.settings.open ? ' dock__item--open' : ''}${topId === 'settings' ? ' dock__item--active' : ''}`}
        onClick={() => desk.dockClick('settings')}
        title="外观设置"
        aria-label="外观设置"
        aria-pressed={desk.state.windows.settings.open}
      >
        <Settings2 size={19} strokeWidth={1.8} />
        <span className="dock__label">外观</span>
        {topId === 'settings' && <span className="dock__dot" />}
      </button>
    </nav>
  )
}
