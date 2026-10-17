import { FolderOpen, Play, Plus } from 'lucide-react'
import type { Desk } from '../useDesk'

/* 唯一示例项目：真实存在的工作台本体，不虚构 */
const PROJECT = {
  name: '个人工作台',
  code: 'personal-workbench',
  desc: '扫描散落在各处的项目，汇成一张清单，每条配方一键启动。工作台的第一块拼图。',
  tags: ['Python', 'FastAPI', '本地网页'],
  path: 'D:\\AI实训project\\个人工作台\\wb',
}

export function ProjectApp({ desk }: { desk: Desk }) {
  return (
    <div className="proj">
      <div className="proj__card">
        <div className="proj__name">
          {PROJECT.name}
          <code>{PROJECT.code}</code>
        </div>
        <p className="proj__desc">{PROJECT.desc}</p>
        <div className="proj__tags">
          {PROJECT.tags.map((t) => (
            <span className="proj__tag" key={t}>{t}</span>
          ))}
        </div>
        <div className="proj__path" title={PROJECT.path}>{PROJECT.path}</div>
        <div className="proj__actions">
          <button className="btn btn--primary" onClick={() => desk.toast('演示原型：此处将启动 personal-workbench')}>
            <Play size={13} strokeWidth={2.4} /> 启动工作台
          </button>
          <button className="btn btn--ghost" onClick={() => desk.toast('演示原型：此处将打开项目文件夹')}>
            <FolderOpen size={13} strokeWidth={2} /> 打开文件夹
          </button>
        </div>
      </div>

      <div className="proj__empty">
        新接入的小工具会陆续出现在这里
        <br />
        <button onClick={() => desk.toast('演示原型：接入方式规划中')}>
          <Plus size={12} strokeWidth={2.2} /> 了解如何接入
        </button>
      </div>
    </div>
  )
}
