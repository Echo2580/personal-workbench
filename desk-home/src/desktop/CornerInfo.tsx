import { useDesk } from './useDesk'

const WEEK = ['日', '一', '二', '三', '四', '五', '六']

/* 演示数据（未接接口） */
const DEMO_WX = { desc: '晴', temp: 18 }

function SunIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="8" cy="8" r="3.2" fill="#E8A33D" />
      <g stroke="#E8A33D" strokeWidth="1.3" strokeLinecap="round">
        <path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M12.6 3.4l-1.1 1.1M4.5 11.5l-1.1 1.1" />
      </g>
    </svg>
  )
}

export function CornerInfo({ desk }: { desk: ReturnType<typeof useDesk> }) {
  const now = new Date()
  return (
    <button
      className="corner"
      onClick={() => {
        if (!desk.state.windows.weather.open) desk.openApp('weather')
        else desk.focus('weather')
      }}
      title="打开天气"
      aria-label="日期与天气，点击打开天气"
    >
      <span className="corner__date">
        {now.getMonth() + 1}月{now.getDate()}日 周{WEEK[now.getDay()]}
      </span>
      <span className="corner__wx">
        <SunIcon />
        <span>{DEMO_WX.desc}</span>
        <b>{DEMO_WX.temp}°</b>
      </span>
    </button>
  )
}
