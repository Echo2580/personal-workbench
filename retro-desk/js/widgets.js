/* js/widgets.js —— 桌面小件：撕页日历 / 今日待办 / 便笺 / 项目文件夹 */
(function () {
  'use strict';
  const RD = window.RD;

  /* ================= 撕页日历 ================= */
  const WEEK = ['日', '一', '二', '三', '四', '五', '六'];

  function renderCalendar() {
    const now = new Date();
    document.getElementById('calWeekday').textContent = '星期' + WEEK[now.getDay()];
    document.getElementById('calDay').textContent = now.getDate();
    document.getElementById('calMonthLabel').textContent = now.getFullYear() + ' 年 ' + (now.getMonth() + 1) + ' 月';
    // 演示天气数据（明确标注）；接真实接口时替换这一行即可
    document.getElementById('calWeather').textContent = '洛阳 · 晴 18°C（演示数据）';

    const mv = document.getElementById('calMonthView');
    mv.innerHTML = '';
    WEEK.forEach(w => {
      const s = document.createElement('span');
      s.className = 'mv-h';
      s.textContent = w;
      mv.appendChild(s);
    });
    const first = new Date(now.getFullYear(), now.getMonth(), 1);
    const days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    for (let i = 0; i < first.getDay(); i++) mv.appendChild(document.createElement('span'));
    for (let d = 1; d <= days; d++) {
      const s = document.createElement('span');
      s.textContent = d;
      if (d === now.getDate()) s.className = 'mv-today';
      mv.appendChild(s);
    }
  }
  renderCalendar();

  document.getElementById('calBody').addEventListener('click', () => {
    document.getElementById('calMonthView').classList.toggle('hidden');
  });

  /* ================= 今日待办 ================= */
  const todoListEl = document.getElementById('todoList');
  const todoMoreBtn = document.getElementById('todoMore');
  const todoForm = document.getElementById('todoForm');
  const todoInput = document.getElementById('todoInput');
  const todoCount = document.getElementById('todoCount');

  let todos = RD.Store.get('todos', null);
  if (!Array.isArray(todos)) {
    todos = [
      { id: 1, text: '给电视换个频道试试', done: false },
      { id: 2, text: '双击打开项目文件夹', done: false },
      { id: 3, text: '戳一下小鲸', done: true }
    ];
  }
  let expanded = false;
  const COLLAPSED_COUNT = 4;

  function saveTodos() { RD.Store.set('todos', todos); }

  function addTodo(text) {
    const t = { id: Date.now() + Math.floor(Math.random() * 1000), text: text, done: false };
    todos.push(t);
    saveTodos();
    renderTodos(t.id);
    return t;
  }

  function renderTodos(newId) {
    todoListEl.innerHTML = '';
    const shown = expanded ? todos : todos.slice(0, COLLAPSED_COUNT);
    shown.forEach(t => {
      const li = document.createElement('li');
      li.className = 'todo-item' + (t.done ? ' done' : '') + (t.id === newId ? ' flash' : '');

      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = t.done;
      cb.addEventListener('change', () => {
        t.done = cb.checked;
        li.classList.toggle('done', t.done);
        saveTodos();
        renderCount();
        if (t.done) RD.Bus.emit('todo:completed', { text: t.text });
      });

      const span = document.createElement('span');
      span.className = 't-text';
      span.textContent = t.text;

      const del = document.createElement('button');
      del.className = 't-del';
      del.type = 'button';
      del.textContent = '×';
      del.title = '删除';
      del.addEventListener('click', () => {
        todos = todos.filter(x => x.id !== t.id);
        saveTodos();
        renderTodos();
      });

      li.appendChild(cb);
      li.appendChild(span);
      li.appendChild(del);
      todoListEl.appendChild(li);
    });

    if (todos.length > COLLAPSED_COUNT) {
      todoMoreBtn.classList.remove('hidden');
      todoMoreBtn.textContent = expanded
        ? '收起'
        : '展开全部（还有 ' + (todos.length - COLLAPSED_COUNT) + ' 条）';
    } else {
      todoMoreBtn.classList.add('hidden');
    }
    renderCount();
  }

  function renderCount() {
    const done = todos.filter(t => t.done).length;
    todoCount.textContent = '已完成 ' + done + ' / ' + todos.length;
  }

  todoMoreBtn.addEventListener('click', () => {
    expanded = !expanded;
    renderTodos();
  });

  todoForm.addEventListener('submit', e => {
    e.preventDefault();
    const text = todoInput.value.trim();
    if (!text) return;
    addTodo(text);
    todoInput.value = '';
  });

  renderTodos();

  /* ================= 便笺 ================= */
  const memoText = document.getElementById('memoText');
  const memoHint = document.getElementById('memoHint');
  let hintTimer = null;

  memoText.value = RD.Store.get('memo', '');

  function showHint(text, isErr) {
    if (hintTimer) clearTimeout(hintTimer);
    memoHint.textContent = text;
    memoHint.style.color = isErr ? '#9c3226' : '#4a6a2a';
    hintTimer = setTimeout(() => { memoHint.textContent = ''; }, 1800);
  }

  document.getElementById('memoSave').addEventListener('click', () => {
    RD.Store.set('memo', memoText.value);
    showHint('已保存 ✓', false);
    RD.Bus.emit('memo:saved');
  });

  document.getElementById('memoToTodo').addEventListener('click', () => {
    const content = memoText.value.trim();
    if (!content) {
      showHint('便笺是空的，先写点内容', true);
      return;
    }
    const text = content.split('\n')[0].slice(0, 40);   // 取首行作为任务
    addTodo(text);
    showHint('已转为待办 →', false);
    RD.Bus.emit('memo:toTodo', { text: text });
  });

  /* ================= 项目文件夹 ================= */
  // ★ 项目入口统一配置处：有地址就填 url，没有就留空（会明确提示未配置）
  const PROJECTS = [
    { name: '个人工作台仓库（GitHub）', url: 'https://github.com/Echo2580/personal-workbench' },
    { name: '启动器原型', url: '' },
    { name: 'FastAPI 学习项目', url: '' }
  ];

  const projectWin = document.getElementById('projectWin');
  const projectList = document.getElementById('projectList');

  function renderProjects() {
    projectList.innerHTML = '';
    PROJECTS.forEach(p => {
      const li = document.createElement('li');
      li.className = 'proj-item';

      const icon = document.createElement('span');
      icon.className = 'p-icon';
      icon.textContent = '📁';

      const name = document.createElement('span');
      name.className = 'p-name';
      name.textContent = p.name;

      const tag = document.createElement('span');
      tag.className = 'p-tag ' + (p.url ? 'ok' : 'none');
      tag.textContent = p.url ? '已配置' : '未配置';

      li.appendChild(icon);
      li.appendChild(name);
      li.appendChild(tag);

      li.addEventListener('click', () => {
        if (p.url) {
          window.open(p.url, '_blank', 'noopener');
        } else {
          // 不伪装成已启动本地程序，明确提示
          showProjHint('「' + p.name + '」尚未配置地址 —— 请在 js/widgets.js 的 PROJECTS 中补充 url');
        }
      });
      projectList.appendChild(li);
    });
    const hint = document.createElement('div');
    hint.className = 'proj-hint';
    hint.id = 'projHint';
    projectList.appendChild(hint);
  }

  let projHintTimer = null;
  function showProjHint(text) {
    const el = document.getElementById('projHint');
    if (!el) return;
    if (projHintTimer) clearTimeout(projHintTimer);
    el.textContent = text;
    projHintTimer = setTimeout(() => { el.textContent = ''; }, 3000);
  }

  function openProjects() {
    projectWin.classList.remove('hidden');
    projectWin.classList.remove('collapsed');
    RD.Bus.emit('win:focus', projectWin);
  }

  renderProjects();

  const folderIcon = document.getElementById('folderIcon');
  folderIcon.addEventListener('dblclick', openProjects);
  folderIcon.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openProjects(); }
  });

  document.getElementById('projectClose').addEventListener('click', () => {
    projectWin.classList.add('hidden');
  });
})();
