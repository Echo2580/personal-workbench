import type { ReactNode } from 'react'

/* ============================================================
   壁纸：全部手绘（CSS 渐变 + SVG），无外部素材，离线可用
   场景壁纸的缩略图与全尺寸桌面共用同一组件，视觉永远一致
   ============================================================ */

export type WallpaperId = 'sunset' | 'mist' | 'night' | 'ridge' | 'oat' | 'slate' | 'charcoal' | 'midnight'

interface WallpaperDef {
  id: WallpaperId
  name: string
  kind: 'scene' | 'solid'
  color?: string
  render?: () => ReactNode
}

/* ---------- 日落大道：poolsuite 的灵魂，暖而不燥 ---------- */
function Sunset() {
  return (
    <div className="wp" style={{ background: 'linear-gradient(to bottom, #3B2A5E 0%, #7E3A6E 34%, #D95F49 62%, #F3A55E 82%, #F7BE7E 100%)' }}>
      <div className="wp__glow" style={{ left: '55%', top: '8%', width: '28%', aspectRatio: '1', background: 'radial-gradient(circle, rgba(255,196,128,0.4) 0%, rgba(255,196,128,0) 68%)' }} />
      <div className="wp__sun" style={{ left: '64%', top: '21%', width: '14%', aspectRatio: '1', background: 'linear-gradient(to bottom, #FFE08A, #FF9E5E)', boxShadow: '0 0 60px rgba(255, 170, 100, 0.55)' }} />
      <div className="wp__sea" style={{ height: '40%', background: 'linear-gradient(to bottom, #4A2E58 0%, #2A1B3E 45%, #191226 100%)' }}>
        <i style={{ top: '12%' }} /><i style={{ top: '26%', opacity: 0.7 }} /><i style={{ top: '44%', opacity: 0.5 }} />
        <i style={{ top: '66%', opacity: 0.35 }} /><i style={{ top: '88%', opacity: 0.22 }} />
        <div className="wp__glow" style={{ left: '57%', top: '0', width: '23%', height: '46%', borderRadius: '40% 40% 50% 50%', background: 'linear-gradient(to bottom, rgba(255,190,120,0.34), rgba(255,190,120,0))' }} />
      </div>
    </div>
  )
}

/* ---------- 薄荷晨雾：浅色、安静 ---------- */
function Mist() {
  return (
    <div className="wp" style={{ background: 'linear-gradient(to bottom, #D7E7E2 0%, #E9EFE4 52%, #F6F1DE 100%)' }}>
      <div className="wp__sun" style={{ right: '16%', top: '14%', width: '7%', aspectRatio: '1', background: 'radial-gradient(circle, #F7E9B0 40%, rgba(247,233,176,0) 72%)' }} />
      <svg className="wp__ridge" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice" style={{ height: '46%' }}>
        <path d="M0 560 Q220 430 430 540 T880 500 T1440 560 V900 H0 Z" fill="#A9C4B4" opacity="0.55" />
        <path d="M0 660 Q300 560 620 650 T1440 640 V900 H0 Z" fill="#8FB19E" opacity="0.6" />
      </svg>
      <div className="wp__sea" style={{ height: '26%', background: 'linear-gradient(to bottom, rgba(246,241,222,0.9), rgba(238,232,210,0.95))' }}>
        <i style={{ top: '30%', opacity: 0.6 }} /><i style={{ top: '58%', opacity: 0.4 }} />
      </div>
    </div>
  )
}

/* ---------- 深夜蓝：星点与一弯月 ---------- */
const NIGHT_STARS: Array<[string, string, string]> = [
  ['8%', '12%', '2px'], ['16%', '24%', '1.5px'], ['23%', '8%', '2.5px'], ['31%', '30%', '1.5px'],
  ['38%', '15%', '2px'], ['46%', '26%', '1.5px'], ['52%', '10%', '2px'], ['61%', '22%', '1.5px'],
  ['68%', '12%', '2.5px'], ['74%', '30%', '1.5px'], ['81%', '16%', '2px'], ['88%', '26%', '1.5px'],
  ['93%', '9%', '2px'], ['12%', '38%', '1.5px'], ['44%', '42%', '1.5px'], ['78%', '40%', '1.5px'],
  ['5%', '20%', '1.5px'], ['35%', '6%', '1.5px'], ['58%', '34%', '2px'], ['86%', '44%', '1.5px'],
]
function Night() {
  return (
    <div className="wp" style={{ background: 'linear-gradient(to bottom, #0D1522 0%, #152436 55%, #1D3048 100%)' }}>
      {NIGHT_STARS.map(([l, t, s], i) => (
        <i key={i} className="wp__star" style={{ left: l, top: t, width: s, height: s, opacity: 0.5 + (i % 3) * 0.15 }} />
      ))}
      {/* SVG 月牙：渐变底色上叠补丁圆的方案会穿帮，改用真实路径 */}
      <svg style={{ position: 'absolute', right: '13%', top: '10%', width: '8%' }} viewBox="0 0 100 100" aria-hidden>
        <path d="M62 8 A44 44 0 1 0 62 92 A35 35 0 1 1 62 8 Z" fill="#F4EFDD" opacity="0.95" />
      </svg>
      <svg className="wp__ridge" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice" style={{ height: '22%' }}>
        <path d="M0 640 Q260 520 520 620 T980 590 T1440 650 V900 H0 Z" fill="#0A1220" />
      </svg>
    </div>
  )
}

/* ---------- 远山：纸感奶油天空 ---------- */
function Ridge() {
  return (
    <div className="wp" style={{ background: 'linear-gradient(to bottom, #F3EAD3 0%, #F8F3E4 60%, #FBF7EC 100%)' }}>
      <svg className="wp__ridge" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice" style={{ height: '62%' }}>
        <path d="M0 520 Q200 380 420 500 T860 460 T1440 540 V900 H0 Z" fill="#D8C6A4" opacity="0.7" />
        <path d="M0 620 Q300 520 640 610 T1440 600 V900 H0 Z" fill="#B4A183" opacity="0.75" />
        <path d="M0 720 Q360 650 700 720 T1440 700 V900 H0 Z" fill="#857763" opacity="0.85" />
      </svg>
    </div>
  )
}

export const WALLPAPERS: WallpaperDef[] = [
  { id: 'sunset', name: '日落大道', kind: 'scene', render: () => <Sunset /> },
  { id: 'mist', name: '薄荷晨雾', kind: 'scene', render: () => <Mist /> },
  { id: 'night', name: '深夜蓝', kind: 'scene', render: () => <Night /> },
  { id: 'ridge', name: '远山', kind: 'scene', render: () => <Ridge /> },
  { id: 'oat', name: '燕麦纸', kind: 'solid', color: '#F1EDE1' },
  { id: 'slate', name: '浅灰', kind: 'solid', color: '#E6E7E3' },
  { id: 'charcoal', name: '炭灰', kind: 'solid', color: '#2A2A2E' },
  { id: 'midnight', name: '午夜蓝', kind: 'solid', color: '#1B2430' },
]

export const DEFAULT_WALLPAPER: WallpaperId = 'sunset'

export function WallpaperView({ id }: { id: WallpaperId }) {
  const def = WALLPAPERS.find((w) => w.id === id) ?? WALLPAPERS[0]
  if (def.kind === 'solid') {
    return <div className="wp" style={{ background: def.color }} />
  }
  return <>{def.render?.()}</>
}
