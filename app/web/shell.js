import {api} from './core/api.js';
import {el,button,icon,modal} from './core/dom.js';
import {notify} from './core/notifications.js';
import {createRouter,navigate} from './core/router.js';
import {moduleLoaders} from './core/module-loaders.js';
import {mount as mountHome} from './pages/home.js';
import {mount as mountSettings} from './pages/settings.js';
export async function requestExit(){
 try{const runs=(await api.request('/system/shutdown-preview')).running_items;
 const content=el('div',{},el('p',{},runs.length?'以下受管理任务将被停止，之后退出工作台：':'退出本地服务？再次使用时双击启动入口。'),el('ul',{},runs.map(r=>el('li',{},r.label))));
 let m;const error=el('p',{role:'alert',class:'error-text'});content.append(error);
 m=modal('退出工作台',content,[button('取消',()=>m.close()),button(runs.length?'停止项目并退出':'确认退出',async e=>{e.currentTarget.disabled=true;try{await api.request('/system/shutdown',{method:'POST',body:{confirmed_stop_running:true}});m.close();document.querySelector('#content').replaceChildren(el('h1',{},'工作台已退出'),el('p',{},'可以关闭此网页。下次双击 start.cmd 打开。'));}catch(ex){error.textContent=ex.message;e.target.disabled=false;}},'danger')]);
 }catch(e){notify(e.message,true);}
}
window.addEventListener('workbench-exit',requestExit);
window.addEventListener('workbench-connection',e=>{document.querySelector('#connection').textContent=e.detail?'本地服务已连接':'服务已断开';document.querySelector('#offline').hidden=e.detail;document.querySelector('#exit').disabled=!e.detail;});
document.querySelector('#settings-nav').onclick=()=>navigate('/settings');document.querySelector('#exit').onclick=requestExit;
document.querySelector('#menu').onclick=()=>{const open=document.querySelector('#sidebar').classList.toggle('open');document.querySelector('#menu').setAttribute('aria-expanded',open);};
async function start(){try{
 const bootstrap=await api.bootstrap();const modules=bootstrap.modules;const navigation=document.querySelector('#navigation');
 const homeNav=button('',()=>navigate('/'),'nav-item',{'data-route':'/',title:'工作台首页'});homeNav.append(icon('home'),el('span',{class:'nav-name'},'工作台首页'));navigation.append(homeNav,el('p',{class:'nav-label'},'功能'));
 for(const m of modules){const n=button('',()=>m.route&&navigate(m.route),'nav-item',{'data-route':m.route||'',disabled:m.status!=='available',title:m.title});n.append(icon(m.icon),el('span',{class:'nav-name'},m.title));if(m.status!=='available')n.append(el('span',{class:'planned'},'规划中'));navigation.append(n);}
 createRouter(async(path,params,signal)=>{
  document.querySelector('#sidebar').classList.remove('open');document.querySelector('#menu').setAttribute('aria-expanded','false');
  const container=document.querySelector('#content');const m=modules.find(m=>m.route===path&&m.status==='available');
  const title=path==='/'?'工作台':path==='/settings'?'设置':m?.title||'页面未找到';document.querySelector('#page-title').textContent=title;document.title=title+' · 个人工作台';
  document.querySelectorAll('[data-route]').forEach(n=>{n.classList.toggle('active',n.dataset.route===path);if(n.dataset.route===path)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});document.querySelector('#settings-nav').classList.toggle('active',path==='/settings');
  const context={api,navigate,notify,signal,modules,params,version:bootstrap.version};container.replaceChildren(el('p',{class:'muted'},'正在加载…'));
  try{if(path==='/')return mountHome(container,context);if(path==='/settings')return await mountSettings(container,context);if(m&&moduleLoaders[m.id]){const loaded=await moduleLoaders[m.id]();if(signal.aborted)return;return loaded.mountPage(container,context);}container.replaceChildren(el('h1',{},'页面未找到'),button('返回工作台',()=>navigate('/')));}catch(e){if(e.name!=='AbortError')container.replaceChildren(el('h1',{},'加载失败'),el('p',{class:'error-text'},e.message),button('重试',()=>location.reload()));}
 });
 }catch(e){document.querySelector('#content').replaceChildren(el('h1',{},'无法连接本地工作台'),el('p',{},e.message),button('重新连接',start));}}
start();
