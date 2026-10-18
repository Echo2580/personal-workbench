import {api} from './core/api.js';
import {el,button,modal} from './core/dom.js';
import {notify} from './core/notifications.js';
import {createRouter,navigate} from './core/router.js';
import {moduleLoaders} from './core/module-loaders.js';
import {sprite,icon} from './core/icons.js';
import {startReminders} from './core/reminders.js';
import {mount as mountHome} from './pages/home.js';
import {mount as mountSettings} from './pages/settings.js';
document.body.prepend(sprite());
document.querySelectorAll('.wb-brand-mark').forEach(n=>n.prepend(icon('widget',18)));
document.querySelector('#brand-leaf')?.prepend(icon('leaf',15));
document.querySelector('#breadcrumb-arrow')?.prepend(icon('alt-arrow-right',13));
document.querySelector('#search-icon')?.prepend(icon('magnifer',16));
document.querySelector('#bell-icon')?.prepend(icon('bell',18));
document.querySelector('#menu-icon')?.prepend(icon('hamburger-menu',20));
document.querySelector('#nav-close-icon')?.prepend(icon('close-circle',19));
document.querySelector('#my-space-arrow')?.prepend(icon('alt-arrow-down',15));
function setNav(open){
  const sidebar=document.querySelector('#sidebar'),backdrop=document.querySelector('#navBackdrop'),menu=document.querySelector('#menu');
  sidebar.classList.toggle('open',open);backdrop.classList.toggle('hidden',!open);
  menu.setAttribute('aria-expanded',String(open));
}
document.querySelector('#menu').onclick=()=>setNav(!document.querySelector('#sidebar').classList.contains('open'));
document.querySelector('#nav-close').onclick=()=>setNav(false);
document.querySelector('#navBackdrop').onclick=()=>setNav(false);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.querySelector('#sidebar').classList.contains('open'))setNav(false);});
document.querySelector('#bell')?.addEventListener('click',()=>{
  const t=document.querySelector('#toast');
  if(!t)return;t.textContent='暂时没有新的通知';t.classList.remove('hidden');t.classList.add('flex');
  clearTimeout(window.__bellTimer);window.__bellTimer=setTimeout(()=>{t.classList.add('hidden');t.classList.remove('flex');},2200);
});
document.querySelector('#my-space')?.addEventListener('click',()=>{
  const t=document.querySelector('#toast');
  if(!t)return;t.textContent='「我的空间」待接入';t.classList.remove('hidden');t.classList.add('flex');
  clearTimeout(window.__spaceTimer);window.__spaceTimer=setTimeout(()=>{t.classList.add('hidden');t.classList.remove('flex');},2200);
});
document.querySelector('#header-avatar')?.addEventListener('click',()=>{
  const t=document.querySelector('#toast');
  if(!t)return;t.textContent='「我的空间」待接入';t.classList.remove('hidden');t.classList.add('flex');
  clearTimeout(window.__avatarTimer);window.__avatarTimer=setTimeout(()=>{t.classList.add('hidden');t.classList.remove('flex');},2200);
});

export async function requestExit(){
 try{const runs=(await api.request('/system/shutdown-preview')).running_items;
 const content=el('div',{},el('p',{},runs.length?'以下受管理任务将被停止，之后退出工作台：':'退出本地服务？再次使用时双击启动入口。'),el('ul',{},runs.map(r=>el('li',{},r.label))));
 let m;const error=el('p',{role:'alert',class:'error-text'});content.append(error);
 m=modal('退出工作台',content,[button('取消',()=>m.close()),button(runs.length?'停止项目并退出':'确认退出',async e=>{e.currentTarget.disabled=true;try{await api.request('/system/shutdown',{method:'POST',body:{confirmed_stop_running:true}});m.close();stopReminders?.();stopReminders=null;document.querySelector('#content').replaceChildren(el('h1',{},'工作台已退出'),el('p',{},'可以关闭此网页。下次双击 start.cmd 打开。'));}catch(ex){error.textContent=ex.message;e.target.disabled=false;}},'danger')]);
 }catch(e){notify(e.message,true);}
}
window.addEventListener('workbench-exit',requestExit);
window.addEventListener('workbench-connection',e=>{document.querySelector('#connection').textContent=e.detail?'本地服务已连接':'服务已断开';document.querySelector('#offline').hidden=e.detail;document.querySelector('#exit').disabled=!e.detail;});

function navItem(label,route,{iconName,disabled=false,planned=false}={}){
 const n=el('button',{type:'button',class:'wb-nav-item','data-route':route||'',title:label},icon(iconName||'widget',17),el('span',{class:'nav-name'},label));
 if(planned)n.append(el('span',{class:'wb-nav-planned'},'规划中'));else n.append(el('span',{class:'wb-nav-dot','aria-hidden':'true'}));
 if(disabled)n.disabled=true;else n.addEventListener('click',()=>route&&navigate(route));
 return n;
}
const settingsNav=document.querySelector('#settings-nav');
settingsNav.prepend(icon('settings',17));
settingsNav.onclick=()=>navigate('/settings');
document.querySelector('#exit').onclick=requestExit;

let stopReminders=null;
async function start(){try{
 const bootstrap=await api.bootstrap();const modules=bootstrap.modules;const navigation=document.querySelector('#navigation');
 navigation.append(el('p',{class:'wb-nav-label'},'工作区'),navItem('工作台首页','/',{iconName:'home-smile'}));
 /* 待办模块拆两个页面：截图转待办（导入/核对）与待办清单（日历/列表/长期任务）。 */
 const EXTRA_NAV={tasks:[{label:'截图转待办',route:'/tasks/import',icon:'image'},{label:'待办清单',route:'/tasks',icon:'checklist'}]};
 const NAV_LABELS={};
 for(const m of modules){
  if(m.id==='tasks'&&m.status==='available'){
   for(const item of EXTRA_NAV.tasks)navigation.append(navItem(item.label,item.route,{iconName:item.icon}));
   continue;
  }
  const planned=m.status!=='available';
  /* 可用但没有导航路由的模块（如首页数据服务）只提供 API，不出现在侧栏。 */
  if(!planned&&!m.route)continue;
  navigation.append(navItem(NAV_LABELS[m.id]||m.title,planned?null:m.route,{iconName:m.icon,disabled:planned,planned}));
 }
 createRouter(async(path,params,signal)=>{
  setNav(false);
  const container=document.querySelector('#content');
  const taskRoute=path==='/tasks'||path==='/tasks/import';
  const m=modules.find(m=>m.route===path&&m.status==='available')||(taskRoute?modules.find(x=>x.id==='tasks'&&x.status==='available'):null);
  const title=path==='/'?'今日总览':path==='/settings'?'设置':path==='/tasks/import'?'截图转待办':path==='/tasks'?'待办清单':m?.title||'页面未找到';document.querySelector('#page-title').textContent=title;document.title=title+' · 个人工作台';
  document.querySelectorAll('[data-route]').forEach(n=>{n.classList.toggle('is-active',n.dataset.route===path);if(n.dataset.route===path)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});settingsNav.classList.toggle('is-active',path==='/settings');
  const context={api,navigate,notify,signal,modules,params,version:bootstrap.version,view:path==='/tasks/import'?'import':path==='/tasks'?'list':undefined};container.className='min-h-0 flex-1 overflow-y-auto overflow-x-hidden'+(path==='/'?' hide-scrollbar':' page-pad');container.replaceChildren(el('p',{class:'muted p-8'},'正在加载…'));
  try{if(path==='/')return mountHome(container,context);if(path==='/settings')return await mountSettings(container,context);if(m&&moduleLoaders[m.id]){const loaded=await moduleLoaders[m.id]();if(signal.aborted)return;return loaded.mountPage(container,context);}container.replaceChildren(el('h1',{},'页面未找到'),button('返回工作台',()=>navigate('/')));}catch(e){if(e.name!=='AbortError')container.replaceChildren(el('h1',{},'加载失败'),el('p',{class:'error-text'},e.message),button('重试',()=>location.reload()));}
 });
 /* 外壳层提醒：待办模块可用时，在任意页面轮询到点提醒（模块页内不再重复开会话）。 */
 const tasksModule=modules.find(m=>m.id==='tasks'&&m.status==='available');
 if(tasksModule&&!stopReminders){try{stopReminders=startReminders({api,navigate});}catch(e){console.error('reminders failed',e);}}
 }catch(e){document.querySelector('#content').replaceChildren(el('h1',{},'无法连接本地工作台'),el('p',{},e.message),button('重新连接',start));}}
start();
