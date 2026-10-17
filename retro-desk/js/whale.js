/* js/whale.js —— 像素鲸鱼「小鲸」
 * 造型：Canvas 逐像素手绘（身体矩阵 + 独立尾巴，可摆尾、眨眼、转向）。
 * 状态机：idle 待机 / move 游动 / nap 打盹 / celebrate 庆祝 / think 思考。
 * 交互：点击（打开聊天）与拖动严格区分；活动范围限定在电视附近，
 *       避开边缘与任务栏；支持整体暂停。
 * 事件互不排队：celebrate 进行中重复触发会被忽略，nod 同理。
 */
(function () {
  'use strict';
  const RD = window.RD;

  const root = document.getElementById('whale');
  const canvas = document.getElementById('whaleCanvas');
  const ctx = canvas.getContext('2d');
  const bubble = document.getElementById('whaleBubble');

  const PX = 4, COLS = 24, ROWS = 14;
  canvas.width = COLS * PX;
  canvas.height = ROWS * PX;

  const COLORS = { B: '#3f7fd6', W: '#eaf3ff', E: '#10233f', T: '#356dbf' };

  // 身体（面朝左，眼睛在左侧）
  const BODY = [
    '........................',
    '.......BB...............',
    '.....BBBBBBBB...........',
    '....BBBBBBBBBB..........',
    '...BBBBBBBBBBBB.........',
    '..BBBBBBBBBBBBBB........',
    '..BEBBBBBBBBBBBBB.......',
    '..BBBBBBBBBBBBBBB.......',
    '..BBBBBBBBBBBBBBB.......',
    '...BBBBBBBBBBWWWW.......',
    '....BBBBBBBWWWWWW.......',
    '.....BBBBWWWWWW.........',
    '.......BWWWW............',
    '........................'
  ];
  // 尾巴（独立绘制，摆动时整体上下偏移 1 像素）
  const TAIL = [
    '....TT',
    '...TTT',
    '..TTTT',
    '.TTTTT',
    'TTTT..'
  ];

  function draw(tailDy, blink, flip) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    if (flip) { ctx.translate(canvas.width, 0); ctx.scale(-1, 1); }
    for (let y = 0; y < ROWS; y++) {
      const row = BODY[y];
      for (let x = 0; x < COLS; x++) {
        const c = row[x];
        if (c === '.') continue;
        if (c === 'E' && blink) {   // 闭眼：一条横线
          ctx.fillStyle = COLORS.E;
          ctx.fillRect((x - 1) * PX, y * PX + 2, PX * 2, 2);
          continue;
        }
        ctx.fillStyle = COLORS[c] || COLORS.B;
        ctx.fillRect(x * PX, y * PX, PX, PX);
      }
    }
    for (let y = 0; y < TAIL.length; y++) {
      const row = TAIL[y];
      for (let x = 0; x < row.length; x++) {
        if (row[x] === '.') continue;
        ctx.fillStyle = COLORS.T;
        ctx.fillRect((17 + x) * PX, (3 + y + tailDy) * PX, PX, PX);
      }
    }
    ctx.restore();
  }

  /* ---------------- 状态机 ---------------- */
  let state = 'idle';       // idle | move | nap | celebrate | think
  let resumeState = 'idle'; // celebrate / think 结束后恢复的状态
  let pos = { x: 200, y: 120 };
  let target = null;
  let afterMove = null;
  let flip = false;
  let tick = 0;
  let blinkUntil = 0, nextBlink = 150;
  let idleUntil = 400;
  let jumpT = -1;           // 庆祝跳跃进度
  let nodT = -1;            // 点头进度
  let petPaused = RD.Store.get('whale.paused', false);
  let dragging = false;

  let region = { x1: 60, y1: 60, x2: 800, y2: 400 };
  let napSpot = { x: 500, y: 100 };

  function computeRegion() {
    const tv = document.getElementById('tv');
    const r = tv.getBoundingClientRect();
    const w = root.offsetWidth || 120;
    const h = root.offsetHeight || 70;
    // 限定在电视上方及两侧，避开底部任务栏与屏幕边缘——
    // 便笺/待办/日历/文件夹都不在这一带，自然不会压住文字和输入区
    region = {
      x1: Math.max(8, r.left - 160),
      x2: Math.max(120, Math.min(window.innerWidth - w - 8, r.right + 80)),
      y1: Math.max(8, r.top - 125),
      y2: Math.max(60, Math.min(window.innerHeight - h - 46, r.top + r.height * 0.4))
    };
    napSpot = { x: Math.min(region.x2, r.right - 40), y: region.y1 + 6 };
    clampPos();
  }

  function clampPos() {
    pos.x = Math.min(Math.max(pos.x, region.x1), Math.max(region.x1, region.x2));
    pos.y = Math.min(Math.max(pos.y, region.y1), Math.max(region.y1, region.y2));
  }

  function setState(s) {
    if (s === 'celebrate') {
      if (state === 'celebrate') return;            // 不排队、不叠加
      if (state !== 'think') resumeState = state === 'nap' ? 'nap' : 'idle';
      state = 'celebrate';
      jumpT = 0;
      return;
    }
    if (s === 'think') {
      if (state === 'celebrate') return;            // 庆祝完再思考
      resumeState = state === 'nap' ? 'nap' : 'idle';
      state = 'think';
      return;
    }
    state = s;
  }

  function nod() {
    if (nodT < 0 && !RD.reduceMotion) nodT = 0;
  }

  function showBubble(text) {
    bubble.textContent = text;
    bubble.classList.remove('hidden');
  }
  function hideBubble() { bubble.classList.add('hidden'); }

  function loop() {
    requestAnimationFrame(loop);
    if (document.hidden) return;
    tick++;

    // 眨眼
    if (tick > nextBlink) {
      blinkUntil = tick + 8;
      nextBlink = tick + 180 + Math.random() * 240;
    }
    const blink = tick < blinkUntil;
    const tailDy = RD.reduceMotion ? 0 : ((tick >> 4) % 2);

    // 点头（便笺保存反馈）
    if (nodT >= 0) {
      canvas.style.transform = 'rotate(' + (Math.sin(nodT / 24 * Math.PI * 2) * 9) + 'deg)';
      nodT++;
      if (nodT > 24) { nodT = -1; canvas.style.transform = ''; }
    }

    // 状态行为
    if (!petPaused && !dragging) {
      if (state === 'move' && target) {
        const dx = target.x - pos.x;
        const dy = target.y - pos.y;
        const dist = Math.hypot(dx, dy);
        if (dist < 5) {
          state = afterMove || 'idle';
          afterMove = null;
          target = null;
          idleUntil = tick + 320 + Math.random() * 500;
        } else {
          pos.x += dx / dist * 1.6;
          pos.y += dy / dist * 1.6;
          flip = dx > 0;
        }
      } else if (state === 'idle' && tick > idleUntil && Math.random() < 0.004 && !RD.reduceMotion) {
        target = {
          x: region.x1 + Math.random() * (region.x2 - region.x1),
          y: region.y1 + Math.random() * (region.y2 - region.y1)
        };
        state = 'move';
      }
    }

    // 位移合成：漂浮 + 庆祝跳跃
    let oy = 0;
    if (!RD.reduceMotion) {
      oy = state === 'nap' ? Math.sin(tick / 55) * 1.5 : Math.sin(tick / 28) * 4;
    }
    if (jumpT >= 0) {
      const J = 80;   // 约 1.3 秒
      oy -= Math.sin((jumpT / J) * Math.PI) * 44;
      jumpT++;
      if (jumpT > J) { jumpT = -1; setState(resumeState); }
    }
    root.style.transform = 'translate(' + pos.x + 'px,' + (pos.y + oy) + 'px)';

    // 气泡
    if (state === 'nap') showBubble('Zzz…');
    else if (state === 'think') showBubble('…');
    else hideBubble();

    draw(tailDy, blink, flip);
  }

  /* ---------------- 点击 / 拖动 ---------------- */
  let grabOffset = null, movedFar = false, downTime = 0;

  root.addEventListener('pointerdown', e => {
    e.preventDefault();
    dragging = true;
    movedFar = false;
    downTime = Date.now();
    grabOffset = { x: e.clientX - pos.x, y: e.clientY - pos.y };
    root.classList.add('dragging');
    try { root.setPointerCapture(e.pointerId); } catch (err) {}
  });

  root.addEventListener('pointermove', e => {
    if (!dragging) return;
    const nx = e.clientX - grabOffset.x;
    const ny = e.clientY - grabOffset.y;
    if (Math.abs(nx - pos.x) + Math.abs(ny - pos.y) > 7) movedFar = true;
    pos.x = nx;
    pos.y = ny;
    clampPos();
  });

  root.addEventListener('pointerup', () => {
    if (!dragging) return;
    dragging = false;
    root.classList.remove('dragging');
    const isClick = !movedFar && (Date.now() - downTime) < 400;
    if (isClick) RD.Bus.emit('whale:click');
  });

  /* ---------------- 联动事件 ---------------- */
  // 完成待办 → 庆祝 1~2 秒
  RD.Bus.on('todo:completed', () => {
    if (!petPaused && !dragging) setState('celebrate');
  });

  // 保存便笺 → 点头回应
  RD.Bus.on('memo:saved', () => {
    if (!petPaused && !dragging) nod();
  });

  // 关电视 → 游到电视旁打盹；开电视 → 醒来
  RD.Bus.on('tv:power', on => {
    if (petPaused || dragging) return;
    if (on) {
      if (state === 'nap') { setState('idle'); idleUntil = tick + 240; }
    } else {
      computeRegion();
      target = { x: napSpot.x, y: napSpot.y };
      afterMove = 'nap';
      setState('move');
      state = 'move';
    }
  });

  // 发起对话 → 思考；收到回复 → 恢复
  RD.Bus.on('chat:sent', () => setState('think'));
  RD.Bus.on('chat:replied', () => {
    if (state === 'think') setState(resumeState === 'nap' ? 'nap' : 'idle');
  });

  /* ---------------- 暂停开关（任务栏） ---------------- */
  const petBtn = document.getElementById('petToggle');
  function renderPetBtn() {
    petBtn.textContent = petPaused ? '恢复鲸鱼' : '暂停鲸鱼';
    petBtn.classList.toggle('active', petPaused);
  }
  petBtn.addEventListener('click', () => {
    petPaused = !petPaused;
    RD.Store.set('whale.paused', petPaused);
    if (petPaused && state === 'move') { state = 'idle'; target = null; }
    renderPetBtn();
  });
  renderPetBtn();

  /* ---------------- 启动 ---------------- */
  function init() {
    computeRegion();
    pos.x = region.x1 + (region.x2 - region.x1) * 0.25;
    pos.y = region.y1 + (region.y2 - region.y1) * 0.4;
    clampPos();
    // 如果电视当前是关着的，直接以打盹姿态启动
    if (!RD.Store.get('tv.power', true)) {
      pos.x = napSpot.x;
      pos.y = napSpot.y;
      state = 'nap';
    }
  }

  window.addEventListener('resize', computeRegion);
  // 等布局稳定后再计算活动范围
  requestAnimationFrame(() => { init(); });
  loop();

  // 暴露给后续扩展（例如后端驱动宠物动作）
  RD.whale = { setState, nod };
})();
