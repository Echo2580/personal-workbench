import {api} from '../../core/api.js';
import {createTasksApp} from './app.js';

/* 「待办清单」模块入口：把 Snap2Todo 的完整前端（导入 → 核对 → 保存 → 列表 →
   详情/原文原图 → 提醒）挂进工作台外壳。
   - view.html：从源 index.html 摘取的 .workspace 四视图 + 提醒弹层 + 错误面板；
   - styles.css：源样式全部作用域化到 .tasks-scope（`:root` 变量也挂在该类上）；
   - app.js：源交互逻辑改造为按实例创建的 createTasksApp(scope, deps)。
   模块内不写 location.hash（内部视图路由只改内存状态），API 一律走 core/api.js
   的 raw()，由它自动补 X-Workbench-Token。 */

const STYLE_ID = 'tasks-module-styles';
const STYLE_URL = '/modules/tasks/styles.css';
const VIEW_URL = '/modules/tasks/view.html';

/* 样式表全局只注入一次（选择器已作用域化，不会影响外壳其它页面）。 */
function ensureStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const link = document.createElement('link');
  link.id = STYLE_ID;
  link.rel = 'stylesheet';
  link.href = STYLE_URL;
  document.head.append(link);
}

async function loadView(signal) {
  const response = await fetch(VIEW_URL, {
    signal,
    cache: 'no-cache',
    headers: {Accept: 'text/html'},
  });
  if (!response.ok) throw new Error(`待办界面模板加载失败（HTTP ${response.status}）。`);
  return response.text();
}

export async function mountPage(container, context) {
  const {signal} = context;
  ensureStyles();
  const html = await loadView(signal);
  if (signal.aborted) return;

  const scope = document.createElement('div');
  scope.className = 'tasks-scope';
  scope.innerHTML = html;

  /* 源页面自带 28/32px 内边距（.page）；工作台 #content 的 page-pad 会再叠一层，
     这里让模块内容铺满内容区，滚动仍由外壳 #content 承担。 */
  container.classList.remove('page-pad');
  container.replaceChildren(scope);

  /* 工作台把待办拆成两个页面：/tasks/import（截图转待办）与 /tasks（待办清单）。
     模块内部视图由 context.view 决定初始落点。 */
  /* 提醒由工作台外壳统一轮询（core/reminders.js），模块内不再重复开会话。 */
  const app = createTasksApp(scope, {
    fetchRaw: (path, options) => api.raw(path, options),
    reminders: false,
  });

  /* 首页「快速记录 → 存为待办」把文本写进 sessionStorage 并跳到这里；
     模块不提供程序化接口，直接操作已挂载的 DOM 完成预填（切到粘贴文字页签）。 */
  let pendingText = '';
  try {
    pendingText = sessionStorage.getItem('wb.pendingTodoText') || '';
    if (pendingText) sessionStorage.removeItem('wb.pendingTodoText');
  } catch (e) { /* 隐私模式忽略 */ }
  if (pendingText) {
    const tabText = scope.querySelector('#tab-text');
    const textarea = scope.querySelector('#import-text');
    if (tabText && textarea) {
      tabText.click();
      textarea.value = pendingText;
      textarea.dispatchEvent(new Event('input', {bubbles: true}));
      textarea.focus();
    }
  }

  if (context.view === "list") app.navigate("#/tasks");
  else if (context.view === "import") app.navigate("#/import");

  let cleaned = false;
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    app.destroy(); // 解绑 window/document 监听、停提醒轮询、关弹层、作废预览 URL
    if (scope.parentNode === container) container.replaceChildren();
  };
  // 路由切换时外壳会 abort；同时外壳也会调用返回的清理函数，两处都做幂等保护。
  signal.addEventListener('abort', cleanup, {once: true});
  return cleanup;
}
