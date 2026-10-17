/* js/drag.js —— 窗口管理：拖动 / 置顶 / 收起恢复 / 整理桌面 / 布局持久化 */
(function () {
  'use strict';
  const RD = window.RD;

  let zCounter = 20;
  const chips = document.getElementById('taskChips');
  const objects = document.querySelectorAll('.desk-object');

  function bringFront(el) {
    zCounter++;
    el.style.zIndex = zCounter;
  }

  // 点击任意物件即置顶（捕获阶段，保证输入框聚焦时也生效）
  objects.forEach(el => {
    el.addEventListener('pointerdown', () => bringFront(el), true);
  });
  RD.Bus.on('win:focus', el => { if (el) bringFront(el); });

  /* ---------------- 拖动 ---------------- */
  objects.forEach(el => {
    const handle = el.querySelector('.drag-handle');
    if (!handle) return;

    handle.addEventListener('pointerdown', e => {
      // 点在按钮 / 输入框 / 旋钮等控件上时不触发拖动
      if (e.target.closest('button, input, textarea, select, a, label, video')) return;
      e.preventDefault();
      bringFront(el);

      const rect = el.getBoundingClientRect();
      const offX = e.clientX - rect.left;
      const offY = e.clientY - rect.top;

      // 从 CSS 默认定位（right / translate）切换为 left/top 绝对定位
      el.style.left = rect.left + 'px';
      el.style.top = rect.top + 'px';
      el.style.right = 'auto';
      el.style.bottom = 'auto';
      el.style.transform = 'none';

      function move(ev) {
        let x = ev.clientX - offX;
        let y = ev.clientY - offY;
        // 不能完全拖出可视区域
        x = Math.min(Math.max(x, -rect.width + 80), window.innerWidth - 80);
        y = Math.min(Math.max(y, 0), window.innerHeight - 48);
        el.style.left = x + 'px';
        el.style.top = y + 'px';
      }
      function up() {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        RD.Store.set('pos.' + el.id, { left: el.style.left, top: el.style.top });
      }
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });

    // 恢复上次布局
    const saved = RD.Store.get('pos.' + el.id, null);
    if (saved && window.innerWidth > 1100) {
      el.style.left = saved.left;
      el.style.top = saved.top;
      el.style.right = 'auto';
      el.style.bottom = 'auto';
      el.style.transform = 'none';
    }
  });

  /* ---------------- 收起 / 恢复 ---------------- */
  document.querySelectorAll('.tb-collapse').forEach(btn => {
    btn.addEventListener('click', () => {
      const win = btn.closest('.desk-object');
      if (!win) return;
      win.classList.add('collapsed');
      const titleEl = win.querySelector('.tb-title');
      const chip = document.createElement('button');
      chip.className = 'chip';
      chip.type = 'button';
      chip.textContent = titleEl ? titleEl.textContent : win.id;
      chip.addEventListener('click', () => {
        win.classList.remove('collapsed');
        win.classList.remove('hidden');
        bringFront(win);
        chip.remove();
      });
      chips.appendChild(chip);
    });
  });

  /* ---------------- 整理桌面 ---------------- */
  document.getElementById('tidyBtn').addEventListener('click', () => {
    RD.Store.removePrefix('pos.');
    objects.forEach(el => {
      el.style.left = '';
      el.style.top = '';
      el.style.right = '';
      el.style.bottom = '';
      el.style.transform = '';
      el.classList.remove('collapsed');
    });
    chips.innerHTML = '';
    zCounter = 20;
  });
})();
