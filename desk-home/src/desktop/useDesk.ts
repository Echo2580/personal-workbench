import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { WallpaperId } from './wallpapers'
import { DEFAULT_WALLPAPER } from './wallpapers'

/* ============================================================
   桌面状态中枢：窗口布局 / 层级 / 显隐 / 用户输入 / 壁纸
   全部持久化到 localStorage，刷新后原样恢复
   ============================================================ */

export type AppId = 'todo' | 'note' | 'calendar' | 'project' | 'weather' | 'settings'

export interface Rect { x: number; y: number; w: number; h: number }

export interface WinState extends Rect {
  open: boolean
  maximized: boolean
  restore: Rect | null
  openedOnce: boolean // 曾打开过：收回后再开恢复原位，不再走锚点级联
}

export interface Todo { id: string; text: string; done: boolean }

export interface WallState {
  id: WallpaperId | 'custom'
  customUrl: string | null
  fit: 'cover' | 'contain'
  dim: number
}

export interface DeskContent {
  todos: Todo[]
  note: string
  wall: WallState
}

interface Persisted {
  v: 1
  windows: Record<AppId, WinState>
  zOrder: AppId[]
  content: DeskContent
}

export interface AppDef {
  id: AppId
  title: string
  dockLabel: string
  min: { w: number; h: number }
  anchor: Rect // 1440×900 设计稿坐标，首次打开使用
  resizable: boolean
  maximizable: boolean
}

export const DOCK_RESERVE = 86 // 底部应用栏 + 安全边距，窗口底不得越过

export const APPS: AppDef[] = [
  { id: 'todo', title: '待办', dockLabel: '待办', min: { w: 240, h: 200 }, anchor: { x: 60, y: 96, w: 316, h: 308 }, resizable: true, maximizable: true },
  { id: 'note', title: '便笺', dockLabel: '便笺', min: { w: 260, h: 220 }, anchor: { x: 412, y: 140, w: 344, h: 300 }, resizable: true, maximizable: true },
  { id: 'calendar', title: '日历', dockLabel: '日历', min: { w: 320, h: 360 }, anchor: { x: 452, y: 84, w: 400, h: 400 }, resizable: true, maximizable: true },
  { id: 'project', title: '项目', dockLabel: '项目', min: { w: 440, h: 340 }, anchor: { x: 232, y: 116, w: 520, h: 412 }, resizable: true, maximizable: true },
  { id: 'weather', title: '天气', dockLabel: '天气', min: { w: 260, h: 240 }, anchor: { x: 1092, y: 92, w: 300, h: 264 }, resizable: false, maximizable: false },
  { id: 'settings', title: '外观设置', dockLabel: '外观', min: { w: 560, h: 460 }, anchor: { x: 372, y: 84, w: 640, h: 560 }, resizable: true, maximizable: true },
]

const APP_MAP = new Map(APPS.map((a) => [a.id, a]))

export function appDef(id: AppId): AppDef {
  return APP_MAP.get(id)!
}

const DEFAULT_TODOS: Todo[] = [
  { id: 't1', text: '把工作台首页原型跑起来', done: true },
  { id: 't2', text: '回复 Issue #4 里日历的讨论', done: false },
  { id: 't3', text: '下楼取快递，顺便买牛奶', done: false },
]

const DEFAULT_NOTE = `十月中旬，洛阳晚上起风了。
今天把首页翻来覆去改了一下午：窗口摆哪儿、留白留多少、鲸鱼放哪角，都试了一遍。最后还是觉得桌面空一点更舒服——东西少了，才敢随便摆。
明天把日历接上。慢慢来。`

const DEFAULT_CONTENT: DeskContent = {
  todos: DEFAULT_TODOS,
  note: DEFAULT_NOTE,
  wall: { id: DEFAULT_WALLPAPER, customUrl: null, fit: 'cover', dim: 1 },
}

function defaultWindows(vw: number, vh: number): Record<AppId, WinState> {
  // 小屏收缩间距、大屏适度铺开；窗口尺寸不缩，保证内容可读
  const kx = Math.max(0.7, (vw - 40) / 1400)
  const ky = Math.max(0.62, (vh - 120) / 780)
  const out = {} as Record<AppId, WinState>
  for (const a of APPS) {
    const x = Math.round(a.anchor.x * kx)
    const y = Math.round(a.anchor.y * ky)
    out[a.id] = { ...a.anchor, x, y, open: a.id === 'todo' || a.id === 'note', maximized: false, restore: null, openedOnce: a.id === 'todo' || a.id === 'note' }
  }
  return out
}

function loadPersisted(vw: number, vh: number): Persisted {
  const fallback: Persisted = { v: 1, windows: defaultWindows(vw, vh), zOrder: ['todo', 'note'], content: DEFAULT_CONTENT }
  try {
    const raw = localStorage.getItem('deskHome.v1')
    if (!raw) return fallback
    const p = JSON.parse(raw) as Persisted
    if (!p || p.v !== 1 || !p.windows || !p.content) return fallback
    // 与当前应用定义合并：新增应用补默认，旧数据不清空用户输入
    const windows = { ...defaultWindows(vw, vh) }
    for (const a of APPS) {
      const saved = p.windows[a.id]
      if (saved && typeof saved.x === 'number') windows[a.id] = { ...saved }
    }
    const zOrder = (p.zOrder ?? []).filter((id) => APP_MAP.has(id))
    for (const a of APPS) if (!zOrder.includes(a.id)) zOrder.push(a.id)
    return { v: 1, windows, zOrder, content: { ...DEFAULT_CONTENT, ...p.content } }
  } catch {
    return fallback
  }
}

/* 演示 / 检查用预设：?demo=multi 三窗叠放，?demo=fresh 完全首次状态，?wall=night 换深夜蓝 */
function applyDemo(p: Persisted, vw: number, vh: number): Persisted {
  if (typeof window === 'undefined') return p
  const q = new URLSearchParams(window.location.search)
  const demo = q.get('demo')
  let out = p
  if (demo === 'fresh') {
    out = { v: 1, windows: defaultWindows(vw, vh), zOrder: ['todo', 'note'], content: DEFAULT_CONTENT }
  }
  if (demo === 'multi') {
    // 三窗阶梯叠放：日历在最底、项目中、天气在最顶，每个都露出标题栏
    const w = { ...out.windows }
    w.calendar = { ...w.calendar, x: 140, y: 80, w: 400, h: 400, open: true, maximized: false }
    w.project = { ...w.project, x: 500, y: 168, w: 520, h: 412, open: true, maximized: false }
    w.weather = { ...w.weather, x: 950, y: 96, w: 300, h: 264, open: true, maximized: false }
    w.todo = { ...w.todo, open: false }
    w.note = { ...w.note, open: false }
    w.settings = { ...w.settings, open: false }
    out = { ...out, windows: w, zOrder: ['calendar', 'project', 'weather'] }
  }
  const wall = q.get('wall')
  if (wall && ['sunset', 'mist', 'night', 'ridge', 'oat', 'slate', 'charcoal', 'midnight'].includes(wall)) {
    out = { ...out, content: { ...out.content, wall: { ...out.content.wall, id: wall as WallpaperId } } }
  }
  return out
}

export function useDesk() {
  const [vw, setVw] = useState(() => (typeof window === 'undefined' ? 1440 : window.innerWidth))
  const [vh, setVh] = useState(() => (typeof window === 'undefined' ? 900 : window.innerHeight))
  const [state, setState] = useState<Persisted>(() => {
    const initial = loadPersisted(window.innerWidth, window.innerHeight)
    return applyDemo(initial, window.innerWidth, window.innerHeight)
  })
  const [entering, setEntering] = useState<AppId | null>(null)
  const [closing, setClosing] = useState<AppId[]>([])
  const [toast, setToast] = useState<{ id: number; text: string } | null>(null)
  const toastTimer = useRef<number | undefined>(undefined)
  const saveTimer = useRef<number | undefined>(undefined)
  const closeTimers = useRef(new Map<AppId, number>())

  /* 视口变化：把窗口夹回可见区域，绝不缩小页面 */
  useEffect(() => {
    const onResize = () => {
      setVw(window.innerWidth)
      setVh(window.innerHeight)
      setState((s) => ({ ...s, windows: clampAll(s.windows, window.innerWidth, window.innerHeight) }))
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  /* 防抖持久化 */
  useEffect(() => {
    window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      try {
        localStorage.setItem('deskHome.v1', JSON.stringify(state))
      } catch { /* 上传壁纸过大等情况：静默降级为本次会话 */ }
    }, 350)
    return () => window.clearTimeout(saveTimer.current)
  }, [state])

  useEffect(() => () => { closeTimers.current.forEach((t) => window.clearTimeout(t)) }, [])

  const showToast = useCallback((text: string) => {
    window.clearTimeout(toastTimer.current)
    setToast({ id: Date.now(), text })
    toastTimer.current = window.setTimeout(() => setToast(null), 2400)
  }, [])

  const zIndexOf = useCallback(
    (id: AppId) => {
      const i = state.zOrder.indexOf(id)
      return 10 + (i < 0 ? 0 : i)
    },
    [state.zOrder],
  )

  const focus = useCallback((id: AppId) => {
    setState((s) =>
      s.zOrder[s.zOrder.length - 1] === id
        ? s
        : { ...s, zOrder: [...s.zOrder.filter((z) => z !== id), id] },
    )
  }, [])

  const openApp = useCallback((id: AppId) => {
    setState((s) => {
      const def = appDef(id)
      const cur = s.windows[id]
      // 曾打开过 → 原位恢复（收回保留位置/大小）；首次打开 → 锚点 + 级联偏移
      let next: WinState
      if (cur.open) {
        next = cur
      } else if (cur.openedOnce) {
        next = { ...cur, open: true, maximized: false }
      } else {
        const openCount = APPS.filter((a) => s.windows[a.id].open).length
        const step = Math.min(openCount, 4)
        next = { ...def.anchor, x: def.anchor.x + step * 34, y: def.anchor.y + step * 30, open: true, maximized: false, restore: null, openedOnce: true }
      }
      return { ...s, windows: { ...s.windows, [id]: next }, zOrder: [...s.zOrder.filter((z) => z !== id), id] }
    })
    setEntering(id)
  }, [])

  useEffect(() => {
    if (!entering) return
    const raf = requestAnimationFrame(() => requestAnimationFrame(() => setEntering(null)))
    return () => cancelAnimationFrame(raf)
  }, [entering])

  const closeApp = useCallback((id: AppId) => {
    setClosing((c) => (c.includes(id) ? c : [...c, id]))
    const t = window.setTimeout(() => {
      setState((s) => ({
        ...s,
        windows: { ...s.windows, [id]: { ...s.windows[id], open: false } },
        // 从层级队列除名：否则已关闭的窗口仍占据"最前面"，dock 的收回/置顶判断会失真
        zOrder: s.zOrder.filter((z) => z !== id),
      }))
      setClosing((c) => c.filter((z) => z !== id))
      closeTimers.current.delete(id)
    }, 130)
    closeTimers.current.set(id, t)
  }, [])

  /* dock 点击规则：未开→展开置顶；最前→收回；被遮→置顶 */
  const dockClick = useCallback((id: AppId) => {
    const w = state.windows[id]
    if (!w.open) openApp(id)
    else if (state.zOrder[state.zOrder.length - 1] === id) closeApp(id)
    else focus(id)
  }, [state.windows, state.zOrder, openApp, closeApp, focus])

  const moveWin = useCallback((id: AppId, x: number, y: number) => {
    setState((s) => ({ ...s, windows: { ...s.windows, [id]: { ...s.windows[id], x, y, maximized: false } } }))
  }, [])

  const resizeWin = useCallback((id: AppId, rect: Rect) => {
    setState((s) => ({ ...s, windows: { ...s.windows, [id]: { ...rect, open: true, maximized: false, restore: null } } }))
  }, [])

  const toggleMaximize = useCallback((id: AppId) => {
    setState((s) => {
      const w = s.windows[id]
      const def = appDef(id)
      if (!def.maximizable) return s
      if (w.maximized && w.restore) {
        return { ...s, windows: { ...s.windows, [id]: { ...w.restore, open: true, maximized: false, restore: null } } }
      }
      const max: Rect = { x: 12, y: 12, w: window.innerWidth - 24, h: window.innerHeight - DOCK_RESERVE }
      return { ...s, windows: { ...s.windows, [id]: { ...max, open: true, maximized: true, restore: { x: w.x, y: w.y, w: w.w, h: w.h } } } }
    })
  }, [])

  /* ---------- 用户输入 ---------- */
  const setTodos = useCallback((updater: (t: Todo[]) => Todo[]) => {
    setState((s) => ({ ...s, content: { ...s.content, todos: updater(s.content.todos) } }))
  }, [])

  const actions = useMemo(
    () => ({
      toggleTodo: (id: string) => setTodos((ts) => ts.map((t) => (t.id === id ? { ...t, done: !t.done } : t))),
      editTodo: (id: string, text: string) => setTodos((ts) => ts.map((t) => (t.id === id ? { ...t, text } : t))),
      addTodo: () =>
        setTodos((ts) => [...ts, { id: `t${Date.now()}`, text: '', done: false }]),
      removeTodo: (id: string) => setTodos((ts) => ts.filter((t) => t.id !== id)),
      setNote: (text: string) => setState((s) => ({ ...s, content: { ...s.content, note: text } })),
      setWall: (patch: Partial<WallState>) =>
        setState((s) => ({ ...s, content: { ...s.content, wall: { ...s.content.wall, ...patch } } })),
      resetWall: () =>
        setState((s) => ({ ...s, content: { ...s.content, wall: { ...DEFAULT_CONTENT.wall } } })),
      resetLayout: () =>
        setState((s) => ({ ...s, windows: defaultWindows(window.innerWidth, window.innerHeight), zOrder: ['todo', 'note'] })),
      toast: showToast,
    }),
    [setTodos, showToast],
  )

  return {
    vw, vh, state, entering, closing, toast,
    zIndexOf, focus, openApp, closeApp, dockClick, moveWin, resizeWin, toggleMaximize,
    ...actions,
  }
}

export type Desk = ReturnType<typeof useDesk>

/* ---------- 边界约束 ---------- */
export function clampRect(r: Rect, vw: number, vh: number, min: { w: number; h: number }): Rect {
  const w = Math.max(min.w, Math.min(r.w, vw - 24))
  const h = Math.max(min.h, Math.min(r.h, vh - DOCK_RESERVE))
  const maxY = vh - DOCK_RESERVE - h
  // y ≥ 0：标题栏永不出屏。正文不响应拖动（防误触），标题栏出屏 = 窗口永久抓不回
  const y = Math.max(0, Math.min(r.y, maxY))
  // 左右至少露出 96px：不允许完全拖出可见区域
  const x = Math.max(-(w - 96), Math.min(r.x, vw - 96))
  return { x, y, w, h }
}

export function clampAll(windows: Record<AppId, WinState>, vw: number, vh: number): Record<AppId, WinState> {
  const out = {} as Record<AppId, WinState>
  for (const a of APPS) {
    const w = windows[a.id]
    out[a.id] = w.maximized
      ? { ...w, x: 12, y: 12, w: vw - 24, h: vh - DOCK_RESERVE }
      : { ...w, ...clampRect(w, vw, vh, a.min) }
  }
  return out
}

export const SNAP_EDGE = 14 // 边缘吸附阈值
export const SNAP_GAP = 12 // 吸附后留的边距

export function snapMove(x: number, y: number, w: number, h: number, vw: number, vh: number) {
  let nx = x
  let ny = y
  if (Math.abs(nx - SNAP_GAP) < SNAP_EDGE) nx = SNAP_GAP
  if (Math.abs(nx - (vw - w - SNAP_GAP)) < SNAP_EDGE) nx = vw - w - SNAP_GAP
  if (Math.abs(ny - SNAP_GAP) < SNAP_EDGE) ny = SNAP_GAP
  const dockY = vh - DOCK_RESERVE - h
  if (Math.abs(ny - dockY) < SNAP_EDGE) ny = dockY
  return { x: nx, y: ny }
}
