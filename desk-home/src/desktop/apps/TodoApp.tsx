import { Plus, X } from 'lucide-react'
import type { Desk } from '../useDesk'

export function TodoApp({ desk }: { desk: Desk }) {
  const todos = desk.state.content.todos
  const done = todos.filter((t) => t.done).length

  return (
    <div className="todo">
      {todos.map((t) => (
        <div className="todo__row" key={t.id}>
          <button
            className={`todo__box${t.done ? ' todo__box--on' : ''}`}
            onClick={() => desk.toggleTodo(t.id)}
            role="checkbox"
            aria-checked={t.done}
            aria-label={t.done ? `标记「${t.text || '新任务'}」为未完成` : `标记「${t.text || '新任务'}」为已完成`}
          >
            {t.done && (
              <svg className="todo__check" width="11" height="9" viewBox="0 0 11 9" aria-hidden>
                <path d="M1 4.5L4 7.5L10 1.5" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </button>
          <input
            className={`todo__text${t.done ? ' todo__text--done' : ''}`}
            value={t.text}
            onChange={(e) => desk.editTodo(t.id, e.target.value)}
            placeholder="写点什么…"
            aria-label="任务内容"
          />
          <button className="todo__del" onClick={() => desk.removeTodo(t.id)} aria-label={`删除「${t.text || '新任务'}」`}>
            <X size={12} strokeWidth={2} />
          </button>
        </div>
      ))}

      <button
        className="todo__add"
        onClick={() => {
          desk.addTodo()
          requestAnimationFrame(() => {
            const rows = document.querySelectorAll<HTMLInputElement>('.todo__text')
            rows[rows.length - 1]?.focus()
          })
        }}
      >
        <Plus size={12} strokeWidth={2.2} /> 加一条
      </button>

      <div className="todo__meta">
        <span>今天的事</span>
        <span>
          <b>{done}</b> / {todos.length} 已完成
        </span>
      </div>
    </div>
  )
}
