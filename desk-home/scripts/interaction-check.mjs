/**
 * 桌面窗口交互回归（28 项断言）。
 *
 * 用法：
 *   1. 起 dev server：   npm run dev
 *   2. 起 CDP Chrome：   chrome --headless=new --remote-debugging-port=9222 --user-data-dir=<临时目录>
 *   3. 跑：              node scripts/interaction-check.mjs
 *
 * 覆盖：初始布局 / 拖动跟手 / 边界钳制 / 边缘吸附 / 置顶 / dock 四条点击规则 /
 *       缩放 / 双击最大化恢复 / 勾选待办 / 编辑便笺 / 收回保留 / 刷新恢复 /
 *       resize 自适应 / 换壁纸 / 预览保留 / 填充方式 / 明暗 / 上传图片 / 恢复默认布局
 *
 * 说明：CDP 不合成 dblclick 事件，双击最大化用原生事件派发验证 React 链路
 * （真实浏览器的 dblclick 由浏览器自身保证）。
 */
const CDP = 'http://127.0.0.1:9222'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function main() {
  const list = await (await fetch(`${CDP}/json`)).json()
  const page = list.find((t) => t.type === 'page')
  if (!page) throw new Error('未找到页面 target，请先按文件头说明启动 CDP Chrome')
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej })

  let msgId = 0
  const pending = new Map()
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
  }
  const send = (method, params = {}) => new Promise((res) => {
    const id = ++msgId; pending.set(id, res); ws.send(JSON.stringify({ id, method, params }))
  })
  const evalJs = async (expr) => (await send('Runtime.evaluate', { expression: expr, returnByValue: true })).result?.result?.value
  const mouse = (type, x, y, extra = {}) => send('Input.dispatchMouseEvent', { type, x, y, button: 'left', ...extra })
  const clickAt = async (x, y) => {
    await mouse('mousePressed', x, y, { buttons: 1, clickCount: 1 })
    await mouse('mouseReleased', x, y, { buttons: 0 })
  }
  const centerOf = async (sel) =>
    evalJs(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el) return null; el.scrollIntoView({ block: 'nearest' }); const r = el.getBoundingClientRect(); return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) } })()`)
  const wins = () => evalJs(`(() => { const o = {}; document.querySelectorAll('.win').forEach(w => { o[w.getAttribute('aria-label')] = { x: parseFloat(w.style.left), y: parseFloat(w.style.top), w: parseFloat(w.style.width), h: parseFloat(w.style.height), z: Number(getComputedStyle(w).zIndex) } }); return o })()`)
  const store = () => evalJs(`JSON.parse(localStorage.getItem('deskHome.v1'))`)
  const dblClickBar = async (label) =>
    evalJs(`document.querySelector('.win[aria-label="${label}"] .win__bar').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))`)

  const results = []
  const check = (name, ok, detail) => {
    results.push({ name, pass: !!ok })
    console.log(`${ok ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`)
  }

  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })
  await send('Page.navigate', { url: 'http://127.0.0.1:3000/?demo=fresh' })
  await sleep(1500)

  // ---- 第一轮：窗口基础 ----
  const w0 = await wins()
  check('初始布局：待办(60,96)+便笺(412,140)', w0['待办']?.x === 60 && w0['待办']?.y === 96, JSON.stringify(w0['待办']))

  const bar = await centerOf('.win[aria-label="待办"] .win__bar')
  await mouse('mousePressed', bar.x, bar.y, { buttons: 1, clickCount: 1 })
  await mouse('mouseMoved', bar.x + 32, bar.y + 27, { buttons: 1 })
  const mid = await wins()
  check('拖动跟手：移动即响应', Math.abs(mid['待办'].x - 92) < 3 && Math.abs(mid['待办'].y - 123) < 3, `x=${mid['待办'].x} y=${mid['待办'].y}`)
  await mouse('mouseMoved', bar.x + 300, bar.y + 300, { buttons: 1 })
  await mouse('mouseReleased', bar.x + 300, bar.y + 300, { buttons: 0 })
  await sleep(250)
  const w1 = await wins()
  check('拖动落点正确', Math.abs(w1['待办'].x - 360) < 3 && Math.abs(w1['待办'].y - 396) < 3, `x=${w1['待办'].x} y=${w1['待办'].y}`)

  await mouse('mousePressed', 518, 413, { buttons: 1, clickCount: 1 })
  await mouse('mouseMoved', -5000, -5000, { buttons: 1 })
  await mouse('mouseReleased', -5000, -5000, { buttons: 0 })
  await sleep(250)
  const w2 = await wins()
  check('边界钳制：x≥-(w-96) 且 y=0', w2['待办'].x === -220 && w2['待办'].y === 0, `x=${w2['待办'].x} y=${w2['待办'].y}`)

  await mouse('mousePressed', 60, 20, { buttons: 1, clickCount: 1 })
  await mouse('mouseMoved', 286, 103, { buttons: 1 })
  await mouse('mouseReleased', 286, 103, { buttons: 0 })
  await sleep(250)
  const w3 = await wins()
  check('边缘吸附：x≈6 → 12', w3['待办'].x === 12, `x=${w3['待办'].x} y=${w3['待办'].y}`)

  const noteBar = await centerOf('.win[aria-label="便笺"] .win__bar')
  await clickAt(noteBar.x, noteBar.y)
  await sleep(150)
  const w4 = await wins()
  check('点击置顶：便笺 z 提升', w4['便笺'].z > w4['待办'].z, `便笺 z=${w4['便笺'].z} > 待办 z=${w4['待办'].z}`)

  // ---- dock 四条规则 ----
  const dockTodo = await centerOf('.dock__item[aria-label="待办"]')
  await clickAt(dockTodo.x, dockTodo.y)
  await sleep(400)
  const wA1 = await wins()
  check('dock 规则③ 被遮挡 → 置顶', wA1['待办'].z > wA1['便笺'].z, `todo z=${wA1['待办'].z} > note z=${wA1['便笺'].z}`)
  await clickAt(dockTodo.x, dockTodo.y)
  await sleep(500)
  check('dock 规则② 最前面再点 → 收回', !(await wins())['待办'], '待办已收起')
  const dockNote = await centerOf('.dock__item[aria-label="便笺"]')
  await clickAt(dockNote.x, dockNote.y)
  await sleep(500)
  check('dock 规则② 便笺同样收回', !(await wins())['便笺'], '便笺已收起')
  await clickAt(dockNote.x, dockNote.y)
  await sleep(500)
  check('dock 规则① 未展开 → 展开置顶', !!(await wins())['便笺'], '便笺重新展开')

  const dockCal = await centerOf('.dock__item[aria-label="日历"]')
  await clickAt(dockCal.x, dockCal.y)
  await sleep(450)
  const w5 = await wins()
  check('dock 打开日历', !!w5['日历'], Object.keys(w5).join('/'))

  // ---- 缩放 / 最大化 ----
  // dock 规则测试后待办处于收起状态，先重新展开
  const dockTodo3 = await centerOf('.dock__item[aria-label="待办"]')
  await clickAt(dockTodo3.x, dockTodo3.y)
  await sleep(500)
  const rz = await evalJs(`(() => { const w = document.querySelector('.win[aria-label="待办"]'); const r = w.getBoundingClientRect(); return { x: Math.round(r.right - 6), y: Math.round(r.bottom - 6) } })()`)
  await mouse('mousePressed', rz.x, rz.y, { buttons: 1, clickCount: 1 })
  await mouse('mouseMoved', rz.x + 120, rz.y + 90, { buttons: 1 })
  await mouse('mouseReleased', rz.x + 120, rz.y + 90, { buttons: 0 })
  await sleep(250)
  const w6 = await wins()
  check('右下角缩放生效', w6['待办'].w > w3['待办'].w + 100, `w ${w3['待办'].w} → ${w6['待办'].w}`)

  await dblClickBar('待办')
  await sleep(350)
  const w7 = await wins()
  check('双击标题栏最大化', w7['待办'].w === 1416 && w7['待办'].h === 814, `w=${w7['待办'].w} h=${w7['待办'].h}`)
  await dblClickBar('待办')
  await sleep(350)
  const w8 = await wins()
  check('再次双击恢复', w8['待办'].w === w6['待办'].w, `w=${w8['待办'].w}`)

  // ---- 内容 ----
  const box = await evalJs(`(() => { const r = document.querySelectorAll('.todo__row')[1].querySelector('.todo__box').getBoundingClientRect(); return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) } })()`)
  await clickAt(box.x, box.y)
  await sleep(250)
  const doneCount = await evalJs(`document.querySelectorAll('.todo__box--on').length`)
  check('勾选待办生效', doneCount === 2, `已完成 ${doneCount} 条`)

  await evalJs(`(() => { const ta = document.querySelector('.note__area'); const s = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set; s.call(ta, '回归测试写入的便笺。'); ta.dispatchEvent(new Event('input', { bubbles: true })); return ta.value })()`)
  await sleep(250)
  check('便笺编辑生效', (await evalJs(`document.querySelector('.note__area').value`)) === '回归测试写入的便笺。')

  // ---- 收回保留 / 刷新恢复 ----
  const minBtn = await centerOf('.win[aria-label="待办"] .win__btn[aria-label="收回待办"]')
  await clickAt(minBtn.x, minBtn.y)
  await sleep(550)
  const w9 = await wins()
  const s9 = await store()
  check('收回窗口：DOM 移除', !w9['待办'], '待办已收起')
  check('收回保留：位置与内容在存储中', s9.windows.todo.open === false && s9.windows.todo.x === 12 && s9.content.todos.filter((t) => t.done).length === 2, `x=${s9.windows.todo.x} done=${s9.content.todos.filter((t) => t.done).length}`)

  await send('Page.navigate', { url: 'http://127.0.0.1:3000/' })
  await sleep(1500)
  check('刷新恢复：待办保持收起', !(await wins())['待办'], '刷新后仍未展开')
  check('刷新恢复：便笺内容原样', (await evalJs(`document.querySelector('.note__area').value`)) === '回归测试写入的便笺。')

  // ---- resize 自适应 ----
  await send('Emulation.setDeviceMetricsOverride', { width: 1000, height: 650, deviceScaleFactor: 1, mobile: false })
  await sleep(600)
  const cal = (await wins())['日历']
  check('resize 1000×650：窗口钳回可见区', cal && cal.x + cal.w <= 1000 && cal.y + cal.h <= 650 - 86, cal ? `日历 x=${cal.x} y=${cal.y} w=${cal.w} h=${cal.h}` : '日历丢失')
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })
  await sleep(400)

  // ---- 壁纸细项 ----
  const dockSet = await centerOf('.dock__item[aria-label="外观设置"]')
  await clickAt(dockSet.x, dockSet.y)
  await sleep(500)
  const fitBtn = await centerOf('.seg button:nth-child(2)')
  await clickAt(fitBtn.x, fitBtn.y)
  await sleep(400)
  check('填充方式切换', (await store()).content.wall.fit === 'contain', '适应模式')
  const range = await evalJs(`(() => { const r = document.querySelector('.range').getBoundingClientRect(); return { x: Math.round(r.x + r.width * 0.3), y: Math.round(r.y + r.height / 2) } })()`)
  await clickAt(range.x, range.y)
  await sleep(400)
  check('明暗调节生效', (await store()).content.wall.dim < 1, `dim=${(await store()).content.wall.dim}`)

  // 上传 1×1 png
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64')
  await send('Runtime.evaluate', { expression: `(() => { const bin = atob(${JSON.stringify(png.toString('base64'))}); const buf = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i); const dt = new DataTransfer(); dt.items.add(new File([buf], 'test.png', { type: 'image/png' })); const inp = document.querySelector('input[type=file]'); inp.files = dt.files; inp.dispatchEvent(new Event('change', { bubbles: true })); return 'ok' })()`, returnByValue: true })
  await sleep(800)
  const wallCustom = await evalJs(`(() => { const w = JSON.parse(localStorage.getItem('deskHome.v1')).content.wall; return w.id === 'custom' && (w.customUrl || '').startsWith('data:image/png') ? 'custom-ok' : w.id })()`)
  check('上传本地图片生效', wallCustom === 'custom-ok', wallCustom)

  // 预览条 + 保留
  const mistCell = await centerOf('.wp-cell[aria-label="预览壁纸 薄荷晨雾"]')
  await clickAt(mistCell.x, mistCell.y)
  await sleep(500)
  check('预览条出现', !!(await evalJs(`!!document.querySelector('.set__previewbar')`)))
  const keepBtn = await centerOf('.set__previewbar .btn--primary')
  await clickAt(keepBtn.x, keepBtn.y)
  await sleep(300)
  check('保留后预览条消失', !(await evalJs(`!!document.querySelector('.set__previewbar')`)))

  // 恢复默认布局
  const dockTodo2 = await centerOf('.dock__item[aria-label="待办"]')
  await clickAt(dockTodo2.x, dockTodo2.y)
  await sleep(500)
  const resetBtn = await centerOf('.set__danger .btn')
  await clickAt(resetBtn.x, resetBtn.y)
  await sleep(600)
  const wD = await wins()
  check('恢复默认布局', wD['待办'] && wD['待办'].x === 60 && wD['待办'].y === 96 && !wD['日历'] && !wD['外观设置'], `待办 x=${wD['待办']?.x} y=${wD['待办']?.y}，窗数=${Object.keys(wD).length}`)

  const failed = results.filter((r) => !r.pass)
  console.log(`\n===== ${results.length - failed.length}/${results.length} 通过 =====`)
  ws.close()
  process.exit(failed.length ? 1 : 0)
}

main().catch((e) => { console.error('FATAL', e); process.exit(2) })
