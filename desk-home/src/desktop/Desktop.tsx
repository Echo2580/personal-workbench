import { CalendarApp } from './apps/CalendarApp'
import { NoteApp } from './apps/NoteApp'
import { ProjectApp } from './apps/ProjectApp'
import { SettingsApp } from './apps/SettingsApp'
import { TodoApp } from './apps/TodoApp'
import { WeatherApp } from './apps/WeatherApp'
import { CornerInfo } from './CornerInfo'
import { Dock } from './Dock'
import { WallpaperView } from './wallpapers'
import { Whale } from './Whale'
import { WindowFrame } from './WindowFrame'
import { APPS, useDesk, type AppId } from './useDesk'

function renderApp(id: AppId, desk: ReturnType<typeof useDesk>) {
  switch (id) {
    case 'todo': return <TodoApp desk={desk} />
    case 'note': return <NoteApp desk={desk} />
    case 'calendar': return <CalendarApp />
    case 'project': return <ProjectApp desk={desk} />
    case 'weather': return <WeatherApp />
    case 'settings': return <SettingsApp desk={desk} />
  }
}

export function Desktop() {
  const desk = useDesk()
  const wall = desk.state.content.wall

  return (
    <div className="desk">
      <div className="wallpaper" style={{ filter: `brightness(${wall.dim})` }}>
        {wall.id === 'custom' && wall.customUrl ? (
          <img src={wall.customUrl} alt="" style={{ objectFit: wall.fit }} />
        ) : (
          <WallpaperView id={wall.id === 'custom' ? 'sunset' : wall.id} />
        )}
      </div>

      <CornerInfo desk={desk} />
      <Whale />

      {APPS.filter((a) => desk.state.windows[a.id].open || desk.closing.includes(a.id)).map((a) => (
        <WindowFrame key={a.id} id={a.id} desk={desk} bodyPad={a.id !== 'note'}>
          {renderApp(a.id, desk)}
        </WindowFrame>
      ))}

      <Dock desk={desk} />

      {desk.toast && (
        <div className="toast" key={desk.toast.id} role="status">
          {desk.toast.text}
        </div>
      )}
    </div>
  )
}
