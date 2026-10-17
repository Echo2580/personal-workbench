import { useRef, useState } from 'react'
import { Check, ImageUp, RotateCcw, Upload } from 'lucide-react'
import type { Desk } from '../useDesk'
import { DEFAULT_WALLPAPER, WALLPAPERS, WallpaperView } from '../wallpapers'

export function SettingsApp({ desk }: { desk: Desk }) {
  const wall = desk.state.content.wall
  const [previewFrom, setPreviewFrom] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const choose = (id: typeof wall.id) => {
    setPreviewFrom(wall.id)
    desk.setWall({ id })
  }

  const onUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (file.size > 4 * 1024 * 1024) {
      desk.toast('图片超过 4MB：本次会话可用，刷新后需重新上传')
    }
    const reader = new FileReader()
    reader.onload = () => {
      setPreviewFrom(wall.id)
      desk.setWall({ id: 'custom', customUrl: reader.result as string })
    }
    reader.readAsDataURL(file)
  }

  const isDefault = wall.id === DEFAULT_WALLPAPER && wall.fit === 'cover' && wall.dim === 1

  return (
    <div>
      <div className="set__group">
        <div className="set__title">
          壁纸
          <small>点击即预览，保留后生效</small>
        </div>
        <div className="wp-grid">
          {WALLPAPERS.map((w) => (
            <button
              key={w.id}
              className={`wp-cell${wall.id === w.id ? ' wp-cell--on' : ''}`}
              onClick={() => choose(w.id)}
              aria-label={`预览壁纸 ${w.name}`}
            >
              <div className="wp-cell__thumb">
                <WallpaperView id={w.id} />
              </div>
              <div className="wp-cell__name">
                {wall.id === w.id && <Check size={11} strokeWidth={2.6} />}
                {w.name}
              </div>
            </button>
          ))}
          {wall.customUrl && (
            <button
              className={`wp-cell${wall.id === 'custom' ? ' wp-cell--on' : ''}`}
              onClick={() => choose('custom')}
              aria-label="预览上传的图片"
            >
              <div className="wp-cell__thumb">
                <img src={wall.customUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              </div>
              <div className="wp-cell__name">
                {wall.id === 'custom' && <Check size={11} strokeWidth={2.6} />}
                我的图片
              </div>
            </button>
          )}
        </div>

        {previewFrom && previewFrom !== wall.id && (
          <div className="set__previewbar">
            <span>正在预览新壁纸</span>
            <span className="set__row">
              <button className="btn btn--primary" style={{ height: 28 }} onClick={() => setPreviewFrom(null)}>
                保留
              </button>
              <button
                className="btn btn--ghost"
                style={{ height: 28 }}
                onClick={() => {
                  desk.setWall({ id: previewFrom as typeof wall.id })
                  setPreviewFrom(null)
                }}
              >
                换回上一张
              </button>
            </span>
          </div>
        )}

        <div className="set__row" style={{ marginTop: 12 }}>
          <button className="btn btn--ghost" onClick={() => fileRef.current?.click()}>
            <Upload size={13} strokeWidth={2} /> 上传本地图片
          </button>
          <input ref={fileRef} type="file" accept="image/*" hidden onChange={onUpload} />
          {!isDefault && (
            <button
              className="btn btn--ghost"
              onClick={() => {
                desk.resetWall()
                setPreviewFrom(null)
                desk.toast('已恢复默认背景')
              }}
            >
              <RotateCcw size={13} strokeWidth={2} /> 恢复默认背景
            </button>
          )}
        </div>
      </div>

      <div className="set__group">
        <div className="set__title">显示</div>
        <div className="set__row" style={{ marginBottom: 12 }}>
          <div className="seg">
            <button className={wall.fit === 'cover' ? 'on' : ''} onClick={() => desk.setWall({ fit: 'cover' })}>
              填充
            </button>
            <button className={wall.fit === 'contain' ? 'on' : ''} onClick={() => desk.setWall({ fit: 'contain' })}>
              适应
            </button>
          </div>
          <span style={{ fontSize: 'var(--fs-small)', color: 'var(--ink-2)' }}>
            {wall.fit === 'cover' ? '等比铺满，裁掉多余部分' : '完整显示，留出底色'}
          </span>
        </div>
        <div className="set__row">
          <ImageUp size={14} color="var(--ink-2)" />
          <input
            className="range"
            type="range"
            min={60}
            max={130}
            step={5}
            value={Math.round(wall.dim * 100)}
            onChange={(e) => desk.setWall({ dim: Number(e.target.value) / 100 })}
            aria-label="壁纸明暗"
          />
          <span className="range__val">{Math.round(wall.dim * 100)}%</span>
        </div>
      </div>

      <div className="set__group">
        <div className="set__title">桌面布局</div>
        <div className="set__danger">
          <p>
            <b>恢复默认布局</b>
            窗口位置、大小和显隐会回到初始状态；待办和便笺内容保留。
          </p>
          <button
            className="btn btn--ghost"
            onClick={() => {
              desk.resetLayout()
              desk.toast('已恢复默认布局')
            }}
          >
            <RotateCcw size={13} strokeWidth={2} /> 恢复
          </button>
        </div>
      </div>
    </div>
  )
}
