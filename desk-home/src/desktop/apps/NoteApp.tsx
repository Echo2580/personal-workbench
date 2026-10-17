import type { Desk } from '../useDesk'

export function NoteApp({ desk }: { desk: Desk }) {
  return (
    <div className="note">
      <div className="note__tape" />
      <textarea
        className="note__area"
        value={desk.state.content.note}
        onChange={(e) => desk.setNote(e.target.value)}
        placeholder="随手写两句…"
        aria-label="便笺内容"
        spellCheck={false}
      />
    </div>
  )
}
