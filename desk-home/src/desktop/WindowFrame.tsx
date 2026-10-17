import { useRef } from 'react'
import type { PointerEvent as ReactPointerEvent, ReactNode } from 'react'
import { Minus, X } from 'lucide-react'
import { appDef, clampRect, snapMove, DOCK_RESERVE, type AppId, type Desk } from './useDesk'

interface Props {
  id: AppId
  desk: Desk
  bodyPad?: boolean
  children: ReactNode
}

export function WindowFrame({ id, desk, bodyPad = true, children }: Props) {
  const def = appDef(id)
  const win = desk.state.windows[id]
  const frameRef = useRef<HTMLDivElement>(null)
  const active = desk.state.zOrder[desk.state.zOrder.length - 1] === id

  /* ---------- 拖动：DOM 直写保证跟手，松手一次性提交 ---------- */
  const onBarPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    const el = frameRef.current
    if (!el) return
    desk.focus(id)
    const startX = e.clientX
    const startY = e.clientY
    const pending = { x: win.x, y: win.y }
    el.classList.add('win--dragging')
    el.setPointerCapture(e.pointerId)

    const onMove = (ev: PointerEvent) => {
      const snapped = snapMove(
        win.x + ev.clientX - startX,
        win.y + ev.clientY - startY,
        win.w,
        win.h,
        desk.vw,
        desk.vh,
      )
      const c = clampRect({ ...snapped, w: win.w, h: win.h }, desk.vw, desk.vh, def.min)
      pending.x = c.x
      pending.y = c.y
      el.style.left = `${c.x}px`
      el.style.top = `${c.y}px`
    }
    const onUp = (ev: PointerEvent) => {
      el.releasePointerCapture(ev.pointerId)
      el.classList.remove('win--dragging')
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', onUp)
      el.removeEventListener('pointercancel', onUp)
      desk.moveWin(id, pending.x, pending.y)
    }
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', onUp)
    el.addEventListener('pointercancel', onUp)
  }

  /* ---------- 缩放：右缘 / 下缘 / 右下角 ---------- */
  const startResize = (dir: 'e' | 's' | 'se') => (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.stopPropagation()
    const el = frameRef.current
    if (!el) return
    desk.focus(id)
    const startX = e.clientX
    const startY = e.clientY
    const pending = { x: win.x, y: win.y, w: win.w, h: win.h }
    el.classList.add('win--resizing')
    el.setPointerCapture(e.pointerId)

    const onMove = (ev: PointerEvent) => {
      let w = win.w
      let h = win.h
      if (dir !== 's') w = win.w + (ev.clientX - startX)
      if (dir !== 'e') h = win.h + (ev.clientY - startY)
      w = Math.max(def.min.w, Math.min(w, desk.vw - 24 - win.x))
      h = Math.max(def.min.h, Math.min(h, desk.vh - DOCK_RESERVE - win.y))
      pending.w = Math.round(w)
      pending.h = Math.round(h)
      el.style.width = `${pending.w}px`
      el.style.height = `${pending.h}px`
    }
    const onUp = (ev: PointerEvent) => {
      el.releasePointerCapture(ev.pointerId)
      el.classList.remove('win--resizing')
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', onUp)
      el.removeEventListener('pointercancel', onUp)
      desk.resizeWin(id, pending)
    }
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', onUp)
    el.addEventListener('pointercancel', onUp)
  }

  const cls = [
    'win',
    active ? 'win--active' : '',
    desk.entering === id ? 'win--enter' : '',
    desk.closing.includes(id) ? 'win--leaving' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div
      ref={frameRef}
      className={cls}
      style={{ left: win.x, top: win.y, width: win.w, height: win.h, zIndex: desk.zIndexOf(id) }}
      onPointerDown={() => desk.focus(id)}
      role="dialog"
      aria-label={def.title}
    >
      <div
        className="win__bar"
        onPointerDown={onBarPointerDown}
        onDoubleClick={(e) => {
          if (def.maximizable) desk.toggleMaximize(id)
          e.stopPropagation()
        }}
      >
        <span className="win__badge" style={{ opacity: active ? 1 : 0.3 }} />
        <span className="win__title">{def.title}</span>
        <div className="win__spacer" />
        <button
          className="win__btn"
          title="收回窗口（内容保留）"
          aria-label={`收回${def.title}`}
          onDoubleClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => {
            desk.focus(id)
            desk.closeApp(id)
          }}
        >
          <Minus size={14} strokeWidth={2.2} />
        </button>
        <button
          className="win__btn win__btn--danger"
          title="关闭窗口（内容保留）"
          aria-label={`关闭${def.title}`}
          onDoubleClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => {
            desk.focus(id)
            desk.closeApp(id)
          }}
        >
          <X size={14} strokeWidth={2.2} />
        </button>
      </div>

      <div className={`win__body${bodyPad ? ' win__body--pad' : ''}`}>{children}</div>

      {def.resizable && !win.maximized && (
        <>
          <div className="win__rz win__rz--e" onPointerDown={startResize('e')} />
          <div className="win__rz win__rz--s" onPointerDown={startResize('s')} />
          <div className="win__rz win__rz--se" onPointerDown={startResize('se')} />
          <svg className="win__grip" viewBox="0 0 12 12" aria-hidden>
            <path d="M11 5L5 11M11 9L9 11" stroke="var(--ink-3)" strokeWidth="1.2" strokeLinecap="round" />
          </svg>
        </>
      )}
    </div>
  )
}
