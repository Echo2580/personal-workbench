/** 外壳层提醒：工作台在任意页面都轮询「到点提醒」，弹层由外壳渲染。
 *
 * 后端契约（待办模块）：
 *   POST /api/v1/reminder-sessions                  → {sessionId, intervalSeconds, startedAt}
 *   GET  /api/v1/reminder-sessions/{id}/due         → {checkedAt, reminders:[{taskId,title,scheduledAt,reminderVersion,...}]}
 *   POST /api/v1/reminders/{taskId}/acknowledgment  → {sessionId, reminderVersion}
 *
 * 语义沿用源产品：提醒只在工作台打开期间有效；会话开始前已到点的不补发；
 * 「稍后」只写本会话去重键，下次真正到点仍会提示（由后端 scheduled/版本控制）。
 */
import {el,button} from './dom.js';
import {icon} from './icons.js';

const STORE_PREFIX = 'wb.rem.';
const SESSION_KEY = 'wb.rem.session';
const FALLBACK_INTERVAL = 5;
const SESSION_TTL_MS = 60 * 60 * 1000;

function memoryStore() {
  const mem = new Map();
  return {get: k => (mem.has(k) ? mem.get(k) : null), set: (k, v) => mem.set(k, v)};
}
function dedupeStore() {
  try {
    if (typeof sessionStorage === 'undefined' || !sessionStorage) return memoryStore();
    return {
      get: k => sessionStorage.getItem(STORE_PREFIX + k),
      set: (k, v) => sessionStorage.setItem(STORE_PREFIX + k, v),
    };
  } catch (e) {
    return memoryStore();
  }
}
const itemKey = item => `${item.taskId}:${item.reminderVersion}`;

/* 提醒会话在标签页之间共享：两个标签各自开会话会互相 supersede，导致 409 循环。 */
function sessionStore() {
  const mem = new Map();
  const fallback = {get: k => (mem.has(k) ? mem.get(k) : null), set: (k, v) => mem.set(k, v), remove: k => mem.delete(k)};
  try {
    if (typeof localStorage === 'undefined' || !localStorage) return fallback;
    return {
      get: k => localStorage.getItem(k),
      set: (k, v) => localStorage.setItem(k, v),
      remove: k => localStorage.removeItem(k),
    };
  } catch (e) {
    return fallback;
  }
}
const sharedSessions = sessionStore();
function readSharedSession() {
  try {
    const raw = sharedSessions.get(SESSION_KEY);
    if (!raw) return null;
    const payload = JSON.parse(raw);
    if (!payload || !payload.sessionId || !payload.at) return null;
    if (Date.now() - Number(payload.at) > SESSION_TTL_MS) return null;
    return payload;
  } catch (e) {
    return null;
  }
}
function writeSharedSession(sessionId, interval) {
  try {
    sharedSessions.set(SESSION_KEY, JSON.stringify({sessionId, interval, at: Date.now()}));
  } catch (e) {
    /* 隐私模式：忽略，退回内存级 */
  }
}
function clearSharedSession(sessionId) {
  const current = readSharedSession();
  if (current && sessionId && current.sessionId !== sessionId) return;
  try {
    sharedSessions.remove(SESSION_KEY);
  } catch (e) {
    /* 忽略 */
  }
}

function readableTime(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  const p = n => String(n).padStart(2, '0');
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay ? `今天 ${p(d.getHours())}:${p(d.getMinutes())}` : `${d.getMonth() + 1}/${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function startReminders({api, navigate, onAck}) {
  const store = dedupeStore();
  const shared = readSharedSession();
  const state = {stopped: false, sessionId: shared ? shared.sessionId : null, timer: null, queue: [], busy: false,
    interval: shared && Number(shared.interval) > 0 ? Number(shared.interval) : FALLBACK_INTERVAL};
  let layer = null;
  let cardHost = null;

  function ensureLayer() {
    if (layer) return layer;
    cardHost = el('div', {class: 'flex flex-col gap-2'});
    layer = el('div', {
      id: 'wb-reminder-layer',
      role: 'alertdialog',
      'aria-live': 'assertive',
      'aria-label': '待办提醒',
      class: 'fixed bottom-5 right-5 z-[95] hidden w-[min(92vw,360px)]',
    }, cardHost);
    document.body.append(layer);
    return layer;
  }

  function hideLayerIfEmpty() {
    if (!layer) return;
    if (cardHost.childElementCount === 0) layer.classList.add('hidden');
  }

  function showCard(item) {
    ensureLayer();
    layer.classList.remove('hidden');
    cardHost.replaceChildren();

    const ackBtn = button('确认', () => acknowledge(item, ackBtn), '', {
      class: 'wb-primary', 'aria-label': `确认提醒：${item.title}`,
    });
    ackBtn.type = 'button';

    const laterBtn = el('button', {
      type: 'button',
      class: 'wb-quiet',
      'aria-label': `稍后提醒：${item.title}`,
    }, '稍后');
    laterBtn.addEventListener('click', () => {
      store.set(itemKey(item), 'later');
      next();
    });

    const openBtn = el('button', {type: 'button', class: 'text-[11px] text-[#5C6E64] underline decoration-[#C9C6B8] underline-offset-2 hover:text-[#244C40]'}, '查看待办');
    openBtn.addEventListener('click', () => {
      if (typeof navigate === 'function') navigate('/tasks');
    });

    const card = el('div', {
      class: 'rounded-2xl border border-[#E3E0D5] bg-white p-4 shadow-[0_16px_40px_rgba(21,36,30,0.22)]',
    },
    el('div', {class: 'flex items-start gap-2.5'},
      el('span', {class: 'mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#EDF3EA] text-[#466453]'}, icon('bell', 16)),
      el('div', {class: 'min-w-0 flex-1'},
        el('p', {class: 'text-[10px] font-medium tracking-[0.12em] text-[#8E9B93]'}, '待办提醒'),
        el('p', {class: 'mt-1 text-[13px] font-medium leading-5 text-[#23342B]'}, item.title || '（无标题）'),
        el('p', {class: 'mt-1 text-[10.5px] text-[#7E8C84]'}, item.scheduledAt ? `提醒时间：${readableTime(item.scheduledAt)}` : '到点提醒'))),
    el('div', {class: 'mt-3 flex items-center justify-end gap-2'}, laterBtn, ackBtn),
    el('div', {class: 'mt-2 flex justify-end'}, openBtn));

    const error = el('p', {class: 'mt-2 hidden text-[10.5px] text-[#B4543B]', role: 'alert'});
    card.append(error);
    card._error = error;
    cardHost.append(card);
  }

  function next() {
    // 只看队列里还没展示过的
    while (state.queue.length) {
      const item = state.queue.shift();
      if (store.get(itemKey(item))) continue;
      store.set(itemKey(item), 'shown');
      showCard(item);
      hideLayerIfEmpty();
      return;
    }
    cardHost?.replaceChildren();
    hideLayerIfEmpty();
  }

  async function acknowledge(item, btn) {
    if (!state.sessionId) return;
    btn.disabled = true;
    try {
      await api.request(`/reminders/${encodeURIComponent(item.taskId)}/acknowledgment`, {
        method: 'POST',
        body: {sessionId: state.sessionId, reminderVersion: item.reminderVersion},
      });
      store.set(itemKey(item), 'ack');
      if (typeof onAck === 'function') onAck(item);
      next();
    } catch (e) {
      const error = cardHost?.firstElementChild?._error;
      if (error) {
        error.textContent = e.message || '确认失败，稍后再试。';
        error.classList.remove('hidden');
      }
      btn.disabled = false;
    }
  }

  async function openSession() {
    // 已有其它标签页共享的会话：直接复用，避免互相 supersede。
    const existing = readSharedSession();
    if (existing) {
      state.sessionId = existing.sessionId;
      state.interval = Number(existing.interval) > 0 ? Number(existing.interval) : FALLBACK_INTERVAL;
      return true;
    }
    try {
      const res = await api.request('/reminder-sessions', {method: 'POST', body: {}});
      const interval = Number(res.intervalSeconds) > 0 ? Number(res.intervalSeconds) : FALLBACK_INTERVAL;
      writeSharedSession(res.sessionId, interval);
      // 并发开会话时以最后写入共享存储的为准，避免两个标签互顶。
      const winner = readSharedSession();
      state.sessionId = winner ? winner.sessionId : res.sessionId;
      state.interval = winner && Number(winner.interval) > 0 ? Number(winner.interval) : interval;
      return true;
    } catch (e) {
      state.sessionId = null;
      return false;
    }
  }

  async function tick() {
    if (state.stopped || state.busy) return;
    if (typeof document !== 'undefined' && document.hidden) return;
    state.busy = true;
    try {
      if (!state.sessionId && !(await openSession())) return;
      const res = await api.request(`/reminder-sessions/${encodeURIComponent(state.sessionId)}/due`);
      const items = (res && res.reminders) || [];
      const fresh = items.filter(item => !store.get(itemKey(item)));
      if (fresh.length) {
        state.queue.push(...fresh);
        if (!cardHost || cardHost.childElementCount === 0) next();
      }
    } catch (e) {
      // 会话失效（服务重启）：下次 tick 重新开会话
      const code = e && e.code;
      if (code === 'reminder_session_not_found' || code === 'reminder_session_superseded' || (e && e.status === 404)) {
        clearSharedSession(state.sessionId);
        state.sessionId = null;
      }
    } finally {
      state.busy = false;
    }
  }

  function schedule() {
    if (state.timer) clearTimeout(state.timer);
    const delay = Math.max(1, state.interval) * 1000;
    state.timer = setTimeout(async () => {
      await tick();
      if (!state.stopped) schedule();
    }, delay);
  }

  function onVisibility() {
    if (document.hidden) return;
    tick();
    schedule();
  }

  document.addEventListener('visibilitychange', onVisibility);
  tick();
  schedule();

  return function stop() {
    state.stopped = true;
    if (state.timer) clearTimeout(state.timer);
    document.removeEventListener('visibilitychange', onVisibility);
    layer?.remove();
    layer = null;
    cardHost = null;
  };
}
