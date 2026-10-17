/* 演示数据，未接接口 */
const FORECAST = [
  { day: '今天', icon: 'sun', desc: '晴', low: 13, high: 21 },
  { day: '周六', icon: 'cloud', desc: '多云', low: 14, high: 20 },
  { day: '周日', icon: 'rain', desc: '小雨', low: 12, high: 17 },
]

function WxIcon({ kind, size = 22 }: { kind: string; size?: number }) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', 'aria-hidden': true } as const
  if (kind === 'sun') {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="4.4" fill="#E8A33D" />
        <g stroke="#E8A33D" strokeWidth="1.6" strokeLinecap="round">
          <path d="M12 2.6v2.2M12 19.2v2.2M2.6 12h2.2M19.2 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6" />
        </g>
      </svg>
    )
  }
  if (kind === 'cloud') {
    return (
      <svg {...common}>
        <path d="M7 18.5h9.5a3.8 3.8 0 0 0 .6-7.6A5.6 5.6 0 0 0 6.4 12 3.4 3.4 0 0 0 7 18.5Z" fill="#B9C4CE" />
      </svg>
    )
  }
  return (
    <svg {...common}>
      <path d="M7 15.5h9.5a3.8 3.8 0 0 0 .6-7.6A5.6 5.6 0 0 0 6.4 9 3.4 3.4 0 0 0 7 15.5Z" fill="#9AA8B5" />
      <g stroke="#5E7A96" strokeWidth="1.6" strokeLinecap="round">
        <path d="M8.5 18l-1 2.4M12.5 18l-1 2.4M16.5 18l-1 2.4" />
      </g>
    </svg>
  )
}

export function WeatherApp() {
  return (
    <div className="wx">
      <div className="wx__now">
        <WxIcon kind="sun" size={38} />
        <div className="wx__temp">
          18<sup>°C</sup>
        </div>
        <div className="wx__meta">
          <span className="wx__city">洛阳</span>
          <span className="wx__desc">晴 · 东北风 2 级</span>
        </div>
      </div>

      <div className="wx__days">
        {FORECAST.map((f) => (
          <div className={`wx__day${f.day === '今天' ? ' wx__day--today' : ''}`} key={f.day}>
            <b>{f.day}</b>
            <WxIcon kind={f.icon} size={16} />
            <span>{f.desc}</span>
            <span>{f.low}° ~ {f.high}°</span>
          </div>
        ))}
      </div>

      <div className="wx__note">演示数据 · 未接入实时天气</div>
    </div>
  )
}
