import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

const WEEK_LABEL = ['日', '一', '二', '三', '四', '五', '六']

export function CalendarApp() {
  const today = new Date()
  const [cursor, setCursor] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1))

  const year = cursor.getFullYear()
  const month = cursor.getMonth()
  const startWd = new Date(year, month, 1).getDay()
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const prevDays = new Date(year, month, 0).getDate()

  const cells: Array<{ day: number; out: boolean }> = []
  for (let i = startWd - 1; i >= 0; i--) cells.push({ day: prevDays - i, out: true })
  for (let d = 1; d <= daysInMonth; d++) cells.push({ day: d, out: false })
  while (cells.length % 7 !== 0 || cells.length < 35) cells.push({ day: cells.length - daysInMonth - startWd + 1, out: true })

  const shift = (delta: number) => setCursor(new Date(year, month + delta, 1))

  return (
    <div>
      <div className="cal__head">
        <div className="cal__month">
          {month + 1}
          <span>月 · {year}</span>
        </div>
        <div className="cal__nav">
          <button className="win__btn" onClick={() => shift(-1)} aria-label="上个月">
            <ChevronLeft size={15} strokeWidth={2} />
          </button>
          <button className="win__btn" onClick={() => shift(1)} aria-label="下个月">
            <ChevronRight size={15} strokeWidth={2} />
          </button>
        </div>
      </div>

      <div className="cal__grid">
        {WEEK_LABEL.map((w) => (
          <div className="cal__wd" key={w}>{w}</div>
        ))}
        {cells.map((c, i) => {
          const isToday = !c.out && year === today.getFullYear() && month === today.getMonth() && c.day === today.getDate()
          return (
            <div
              key={i}
              className={`cal__cell${c.out ? ' cal__cell--out' : ''}${isToday ? ' cal__cell--today' : ''}`}
              aria-label={isToday ? `今天，${c.day}日` : undefined}
            >
              {c.day}
            </div>
          )
        })}
      </div>

      <div className="cal__foot">
        今天是 <b>{today.getMonth() + 1} 月 {today.getDate()} 日</b> · 周{WEEK_LABEL[today.getDay()]}
      </div>
    </div>
  )
}
