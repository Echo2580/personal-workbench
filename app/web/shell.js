import {api} from './core/api.js';
import {el,button,modal} from './core/dom.js';
import {notify} from './core/notifications.js';
import {createRouter,navigate} from './core/router.js';
import {moduleLoaders} from './core/module-loaders.js';
import {sprite,icon} from './core/icons.js';
import {startReminders} from './core/reminders.js';
import {mountGlobalSearch} from './core/global-search.js';
import {mount as mountHome} from './pages/home.js';
import {mount as mountSettings} from './pages/settings.js';
document.body.prepend(sprite());
document.querySelectorAll('.wb-brand-mark').forEach(n=>n.prepend(icon('checklist',17)));
const headerDate=document.querySelector('#header-date');
function updateHeaderDate(){const d=new Date();headerDate.dateTime=d.toISOString();headerDate.textContent=d.getFullYear()+'年'+(d.getMonth()+1)+'月'+d.getDate()+'日 · '+['周日','周一','周二','周三','周四','周五','周六'][d.getDay()];}
updateHeaderDate();setInterval(updateHeaderDate,60000);
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
/* ===== 我的空间：头像下拉面板（个人资料 / 今日概览 / 快捷操作） ===== */
const DEFAULT_PROFILE={displayName:'林同学',signature:'个人版'};
const profile={...DEFAULT_PROFILE};
let spacePanel=null,spaceOpen=false,spaceTrigger=null,spaceEditing=null,spaceOverviewSeq=0;
let spaceAvatarEl=null,spaceNameBtn=null,spaceSigBtn=null,spaceNameSlot=null,spaceSigSlot=null;
let spaceOverviewEl=null,statTasks=null,statNotes=null,statProjects=null;

function profileInitial(){
  const chars=Array.from((profile.displayName||'').trim()||'我');
  return chars[0]||'我';
}
function applyProfile(){
  document.querySelectorAll('[data-profile-initial]').forEach(node=>{node.textContent=profileInitial();});
  const headerAvatar=document.querySelector('#header-avatar');
  if(headerAvatar)headerAvatar.setAttribute('aria-label','我的空间：'+(profile.displayName||DEFAULT_PROFILE.displayName));
  const mobileAvatar=document.querySelector('#mobile-avatar');
  if(mobileAvatar)mobileAvatar.setAttribute('aria-label','我的空间：'+(profile.displayName||DEFAULT_PROFILE.displayName));
  const sidebarProfile=document.querySelector('#my-space-profile');
  if(sidebarProfile)sidebarProfile.textContent=(profile.displayName||DEFAULT_PROFILE.displayName)+(profile.signature?' · '+profile.signature:'');
  const sidebar=document.querySelector('#my-space');
  if(sidebar)sidebar.setAttribute('aria-label','我的空间：'+(profile.displayName||DEFAULT_PROFILE.displayName));
  if(spacePanel&&!spaceEditing)renderSpaceIdentity();
}
function setSpaceExpanded(value){
  for(const node of [document.querySelector('#header-avatar'),document.querySelector('#mobile-avatar'),document.querySelector('#my-space')]){
    if(node)node.setAttribute('aria-expanded',String(value));
  }
}

function renderSpaceIdentity(){
  if(!spaceAvatarEl)return;
  spaceAvatarEl.textContent=profileInitial();
  spaceNameBtn.textContent=profile.displayName||DEFAULT_PROFILE.displayName;
  spaceNameBtn.hidden=Boolean(spaceEditing&&spaceEditing.field==='displayName');
  spaceSigBtn.textContent=profile.signature||'写一句签名';
  spaceSigBtn.classList.toggle('is-empty',!profile.signature);
  spaceSigBtn.hidden=Boolean(spaceEditing&&spaceEditing.field==='signature');
}
function endSpaceEdit(){
  if(!spaceEditing)return;
  const {input,field}=spaceEditing;
  spaceEditing=null;
  if(input&&input.parentNode)input.remove();
  renderSpaceIdentity();
  /* Enter/Esc 结束后输入框被移除，焦点若落回 body 则还给对应按钮；点别处失焦时不抢焦点。 */
  const button=field==='displayName'?spaceNameBtn:spaceSigBtn;
  if(button&&(document.activeElement===document.body||!document.activeElement))button.focus();
}
function cancelSpaceEdit(){if(spaceEditing)endSpaceEdit();}
async function commitSpaceEdit(){
  const editing=spaceEditing;
  if(!editing||editing.saving)return;
  const isName=editing.field==='displayName';
  let value=(editing.input.value||'').replace(/[\r\n\t]/g,'').trim();
  value=value.slice(0,isName?20:40);
  if(isName&&!value){notify('显示名不能为空',true);editing.input.focus();return;}
  const previous=isName?profile.displayName:profile.signature;
  if(value===previous){endSpaceEdit();return;}
  editing.saving=true;
  try{
    const data=await api.request('/preferences',{method:'PUT',body:{profile:{[editing.field]:value}}});
    const saved=(data&&data.profile)||{};
    if(typeof saved.displayName==='string')profile.displayName=saved.displayName;
    if(typeof saved.signature==='string')profile.signature=saved.signature;
    endSpaceEdit();
    applyProfile();
    notify(isName?'显示名已更新':'签名已更新');
  }catch(e){
    endSpaceEdit();
    applyProfile();
    notify(e.message||'保存失败',true);
  }
}
function startSpaceEdit(field){
  if(spaceEditing)return;
  const isName=field==='displayName';
  const button=isName?spaceNameBtn:spaceSigBtn;
  const slot=isName?spaceNameSlot:spaceSigSlot;
  const input=el('input',{type:'text',class:'wb-space-input',autocomplete:'off',maxLength:isName?20:40,value:isName?profile.displayName:profile.signature,placeholder:isName?'显示名':'写一句签名','aria-label':isName?'显示名，回车保存，Esc 取消':'签名，回车保存，Esc 取消'});
  spaceEditing={field,input,saving:false};
  button.hidden=true;
  slot.append(input);
  input.focus();
  try{input.setSelectionRange(input.value.length,input.value.length);}catch(e){/* 部分输入法忽略 */}
  input.addEventListener('keydown',event=>{
    if(event.isComposing||event.keyCode===229)return;
    if(event.key==='Enter'){event.preventDefault();event.stopPropagation();commitSpaceEdit();}
    else if(event.key==='Escape'){event.preventDefault();event.stopPropagation();cancelSpaceEdit();}
  });
  input.addEventListener('blur',()=>{if(spaceEditing&&spaceEditing.input===input&&!spaceEditing.saving)commitSpaceEdit();});
}

function spaceStatCell(){
  const value=el('strong',{class:'wb-space-stat-value'},'…');
  const label=el('span',{class:'wb-space-stat-label'},'读取中');
  return {node:el('div',{class:'wb-space-stat'},value,label),value,label};
}
function setSpaceStat(stat,value,label){if(!stat)return;stat.value.textContent=String(value);stat.label.textContent=label;}
function failSpaceStat(stat,name){setSpaceStat(stat,'—',name+' · 暂不可用');}
function renderSpaceOverviewLoading(){
  if(!spaceOverviewEl)return;
  statTasks=spaceStatCell();statNotes=spaceStatCell();statProjects=spaceStatCell();
  spaceOverviewEl.replaceChildren(statTasks.node,statNotes.node,statProjects.node);
}
function dayKeyOf(date){return date.getFullYear()+'-'+String(date.getMonth()+1).padStart(2,'0')+'-'+String(date.getDate()).padStart(2,'0');}
function taskDateKey(task){
  for(const moment of [task&&task.dueTime&&task.dueTime.resolvedValue,task&&task.startTime&&task.startTime.resolvedValue]){
    if(!moment)continue;
    const date=new Date(moment);
    if(!Number.isNaN(date.getTime()))return dayKeyOf(date);
  }
  return null;
}
/* 与首页同一口径：今天到期 + 逾期未完成；无日期不计入。 */
function todayTaskStats(tasks){
  const key=dayKeyOf(new Date());
  let done=0,total=0;
  for(const task of tasks){
    const date=taskDateKey(task);
    if(!date)continue;
    const completed=task&&task.status==='completed';
    if(date===key||(!completed&&date<key)){total+=1;if(completed)done+=1;}
  }
  return {done,total};
}
async function loadSpaceOverview(){
  if(!spacePanel)return;
  const seq=++spaceOverviewSeq;
  renderSpaceOverviewLoading();
  const [tasksResult,notesResult,projectsResult,runningResult]=await Promise.allSettled([
    api.request('/tasks?status=all'),
    api.request('/notes'),
    api.request('/projects'),
    api.request('/system/shutdown-preview'),
  ]);
  if(seq!==spaceOverviewSeq||!spacePanel)return;
  if(tasksResult.status==='fulfilled'){
    const stats=todayTaskStats((tasksResult.value&&tasksResult.value.tasks)||[]);
    setSpaceStat(statTasks,stats.done+' / '+stats.total,'今日待办');
    statTasks.node.title='今日已完成 '+stats.done+' / 共 '+stats.total+' 条今日待办（含逾期）';
  }else failSpaceStat(statTasks,'今日待办');
  if(notesResult.status==='fulfilled'){
    const items=(notesResult.value&&notesResult.value.items)||[];
    setSpaceStat(statNotes,items.length,'随手记');
    statNotes.node.title='共 '+items.length+' 条随手记';
  }else failSpaceStat(statNotes,'随手记');
  if(projectsResult.status==='fulfilled'){
    const projects=((projectsResult.value&&projectsResult.value.projects)||[]).filter(item=>item&&!item.removed_at);
    const running=runningResult.status==='fulfilled'
      ? (((runningResult.value&&runningResult.value.running_items)||[]).length)
      : null;
    setSpaceStat(statProjects,projects.length,running==null?'项目':('项目 · 运行 '+running));
    statProjects.node.title='已发现 '+projects.length+' 个项目'+(running==null?'':'，运行中 '+running+' 个');
  }else failSpaceStat(statProjects,'项目');
}

function ensureSpacePanel(){
  if(spacePanel)return spacePanel;
  spaceAvatarEl=el('span',{class:'wb-space-avatar','aria-hidden':'true'},profileInitial());
  spaceNameBtn=el('button',{type:'button',class:'wb-space-name',title:'编辑显示名','aria-label':'编辑显示名'},profile.displayName);
  spaceSigBtn=el('button',{type:'button',class:'wb-space-sign',title:'编辑签名','aria-label':'编辑签名'},profile.signature||'写一句签名');
  spaceNameSlot=el('div',{class:'wb-space-field'},spaceNameBtn);
  spaceSigSlot=el('div',{class:'wb-space-field'},spaceSigBtn);
  spaceOverviewEl=el('div',{class:'wb-space-overview'});
  spacePanel=el('div',{id:'mySpacePanel',class:'wb-space-panel hidden',role:'dialog','aria-label':'我的空间'},
    el('div',{class:'wb-space-head'},spaceAvatarEl,el('div',{class:'wb-space-identity'},spaceNameSlot,spaceSigSlot)),
    el('p',{class:'wb-space-label'},'今日概览'),
    spaceOverviewEl,
    el('div',{class:'wb-space-actions'},
      el('button',{type:'button',class:'wb-space-action',onClick:()=>{closeSpacePanel({focusBack:false});navigate('/settings');}},icon('settings',15),el('span',{},'设置')),
      el('button',{type:'button',class:'wb-space-action is-danger',onClick:()=>{closeSpacePanel({focusBack:false});window.dispatchEvent(new Event('workbench-exit'));}},icon('close-circle',15),el('span',{},'退出工作台'))));
  document.body.append(spacePanel);
  spaceNameBtn.addEventListener('click',()=>startSpaceEdit('displayName'));
  spaceSigBtn.addEventListener('click',()=>startSpaceEdit('signature'));
  renderSpaceIdentity();
  renderSpaceOverviewLoading();
  return spacePanel;
}
function positionSpacePanel(){
  if(!spacePanel||!spaceOpen)return;
  const trigger=spaceTrigger&&spaceTrigger.isConnected?spaceTrigger:document.querySelector('#header-avatar');
  const rect=trigger?trigger.getBoundingClientRect():{bottom:64,right:window.innerWidth-22};
  const header=document.querySelector('.wb-header');
  const headerBottom=header?header.getBoundingClientRect().bottom:0;
  const width=Math.min(window.innerWidth*0.92,340);
  const top=Math.round(Math.max(rect.bottom+8,headerBottom+6));
  const right=Math.round(Math.max(8,Math.min(window.innerWidth-rect.right,window.innerWidth-width-8)));
  spacePanel.style.top=top+'px';
  spacePanel.style.right=right+'px';
  spacePanel.style.left='auto';
  spacePanel.style.maxHeight=Math.max(180,window.innerHeight-top-12)+'px';
}
function openSpacePanel(trigger){
  ensureSpacePanel();
  if(spaceOpen){positionSpacePanel();return;}
  spaceTrigger=trigger||document.querySelector('#header-avatar');
  spaceOpen=true;
  spacePanel.classList.remove('hidden');
  setSpaceExpanded(true);
  renderSpaceIdentity();
  positionSpacePanel();
  loadSpaceOverview();
  (spaceNameBtn||spacePanel).focus();
}
function closeSpacePanel({focusBack=true}={}){
  if(!spaceOpen)return;
  spaceOpen=false;
  cancelSpaceEdit();
  setSpaceExpanded(false);
  if(spacePanel)spacePanel.classList.add('hidden');
  if(focusBack&&spaceTrigger&&spaceTrigger.isConnected)spaceTrigger.focus();
}
function toggleSpacePanel(trigger){if(spaceOpen)closeSpacePanel();else openSpacePanel(trigger);}
for(const selector of ['#header-avatar','#mobile-avatar','#my-space']){
  document.querySelector(selector)?.addEventListener('click',event=>{event.stopPropagation();toggleSpacePanel(event.currentTarget);});
}
document.addEventListener('click',event=>{
  if(!spaceOpen)return;
  if(spacePanel&&spacePanel.contains(event.target))return;
  if(event.target.closest&&event.target.closest('#header-avatar,#mobile-avatar,#my-space'))return;
  closeSpacePanel({focusBack:false});
});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&spaceOpen)closeSpacePanel();
});
window.addEventListener('resize',()=>{if(spaceOpen)positionSpacePanel();});
async function loadProfile(){
  try{
    const data=await api.request('/preferences');
    const saved=(data&&data.profile)||{};
    if(typeof saved.displayName==='string'&&saved.displayName.trim())profile.displayName=saved.displayName;
    if(typeof saved.signature==='string')profile.signature=saved.signature;
  }catch(e){/* 读取失败沿用默认资料，不阻塞外壳 */}
  applyProfile();
}
applyProfile();

export async function requestExit(){
 try{const runs=(await api.request('/system/shutdown-preview')).running_items;
 const content=el('div',{},el('p',{},runs.length?'以下受管理任务将被停止，之后退出工作台：':'退出本地服务？再次使用时双击启动入口。'),el('ul',{},runs.map(r=>el('li',{},r.label))));
 let m;const error=el('p',{role:'alert',class:'error-text'});content.append(error);
 m=modal('退出工作台',content,[button('取消',()=>m.close()),button(runs.length?'停止项目并退出':'确认退出',async e=>{e.currentTarget.disabled=true;try{await api.request('/system/shutdown',{method:'POST',body:{confirmed_stop_running:true}});m.close();stopReminders?.();stopReminders=null;stopSearch?.();stopSearch=null;document.querySelector('#content').replaceChildren(el('h1',{},'工作台已退出'),el('p',{},'可以关闭此网页。下次双击 start.cmd 打开。'));}catch(ex){error.textContent=ex.message;e.target.disabled=false;}},'danger')]);
 }catch(e){notify(e.message,true);}
}
window.addEventListener('workbench-exit',requestExit);
window.addEventListener('workbench-connection',e=>{document.querySelector('#connection').textContent=e.detail?'本地服务已连接':'服务已断开';document.querySelector('#offline').hidden=e.detail;document.querySelector('#exit').disabled=!e.detail;});

function navItem(label,route,{iconName,disabled=false,planned=false}={}){
 const n=el('button',{type:'button',class:'wb-nav-item','data-route':route||'',title:label},icon(iconName||'widget',17),el('span',{class:'nav-name'},label));
 if(planned)n.append(el('span',{class:'wb-nav-planned'},'规划中'));else n.append(el('span',{class:'wb-nav-dot','aria-hidden':'true'}));
 if(disabled)n.disabled=true;else n.addEventListener('click',()=>{setNav(false);if(route)navigate(route);});
 return n;
}
const settingsNav=document.querySelector('#settings-nav');
settingsNav.prepend(icon('settings',17));
settingsNav.onclick=()=>{setNav(false);navigate('/settings');};
document.querySelector('#exit').onclick=requestExit;

let stopReminders=null,stopSearch=null;
async function start(){try{
 const bootstrap=await api.bootstrap();const modules=bootstrap.modules;const navigation=document.querySelector('#navigation');
 loadProfile().catch(()=>{});
 stopSearch?.();stopSearch=mountGlobalSearch({api,navigate});
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
