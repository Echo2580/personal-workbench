import {el,button,poll} from '../core/dom.js';
import {icon} from '../core/icons.js';

/* 今日总览仪表盘。
   待办卡片接真实模块数据（/api/v1/tasks）；天气/梗词/日程/随手记仍是界面占位，
   数据源在后续功能接入。常用入口接 bootstrap modules 真实数据。 */

const state={
  filter:'all',selectedDay:18,city:'南京',memeIndex:0,
  noteLines:['天气、热梗、待办都放在一屏。','少一点切换，多一点顺手。'],
  memes:[
    {word:'班味',desc:'一种上完班后，连周末都想静音的气质。',usage:'周六醒来，看到工作群消息，整个人突然就有了班味。',items:[{word:'情绪价值',desc:'为情绪买单，也愿意为情绪充电。'},{word:'松弛感',desc:'不慌不忙，允许一切发生。'}]},
    {word:'电子榨菜',desc:'吃饭时必不可少的下饭视频，没它饭都不香。',usage:'午饭准备好了，先打开收藏夹挑一集电子榨菜。',items:[{word:'赛博散步',desc:'不设目的地，在网页和地图里随便走走。'},{word:'低电量社交',desc:'只参加不用努力找话题的见面。'}]},
    {word:'淡人',desc:'情绪稳定、欲望不高，对很多事都可以。',usage:'问他周末去哪，他说都行，典型淡人发言。',items:[{word:'轻断网',desc:'主动离开消息流几个小时。'},{word:'微退休',desc:'在忙碌日常里，给自己安排一小段空白。'}]},
  ],
};
const cities={
  '南京':{temp:23,condition:'晴间多云',low:18,high:25,aqi:'空气优',tip:'适合出门走走',forecast:[23,25,24,21]},
  '杭州':{temp:24,condition:'多云',low:19,high:27,aqi:'空气良',tip:'湖边风正舒服',forecast:[24,27,26,22]},
  '苏州':{temp:22,condition:'晴',low:17,high:24,aqi:'空气优',tip:'适合慢走',forecast:[22,24,23,20]},
  '上海':{temp:25,condition:'晴间多云',low:21,high:28,aqi:'空气优',tip:'江风正好',forecast:[25,28,27,23]},
};
const WEEKDAYS=['周日','周一','周二','周三','周四','周五','周六'];
const searchData={
  projects:[{name:'个人工作台首页原型',meta:'项目 · 最近编辑'},{name:'毕业设计需求文档',meta:'项目 · 昨天更新'}],
  tools:[{name:'Figma',meta:'设计工具'},{name:'Notion',meta:'知识整理'},{name:'GitHub',meta:'代码与项目'}],
  notes:[{name:'首页想法',meta:'随手记 · 今天'},{name:'本周效率复盘',meta:'笔记 · 10 月 16 日'}],
};

function toast(msg){
  const t=document.querySelector('#toast');if(!t)return;
  t.textContent=msg;t.classList.remove('hidden');t.classList.add('flex');
  clearTimeout(toast.timer);toast.timer=setTimeout(()=>{t.classList.add('hidden');t.classList.remove('flex');},2200);
}
function mkOverlay(id,inner){
  const ov=el('div',{id,role:'dialog','aria-modal':'true',class:'fixed inset-0 z-[70] hidden items-center justify-center bg-[#15241E]/45 p-4'});
  ov.append(el('div',{class:'w-full max-w-[520px] rounded-2xl border border-[#E5E1D6] bg-[#FEFDF9] p-6 shadow-2xl'},...inner));
  ov.addEventListener('click',e=>{if(e.target===ov){ov.classList.add('hidden');ov.classList.remove('flex');}});
  document.body.append(ov);return ov;
}
function openOv(ov){ov.classList.remove('hidden');ov.classList.add('flex');}
function closeOv(ov){ov.classList.add('hidden');ov.classList.remove('flex');}

export function mount(container,context){
  const now=new Date();
  const dateLine=`${now.getMonth()+1} 月 ${now.getDate()} 日・${WEEKDAYS[now.getDay()]}`;
  const calendarDays=[];
  for(let d=now.getDate()-6;d<=now.getDate();d++){
    calendarDays.push({day:d,label:WEEKDAYS[new Date(now.getFullYear(),now.getMonth(),d).getDay()]});
  }
  state.selectedDay=now.getDate();
  const SCHEDULE_POOL=[
    [{time:'09:30',title:'一周计划同步',place:'线上会议'},{time:'16:00',title:'需求资料整理',place:'个人项目'}],
    [{time:'10:00',title:'界面设计评审',place:'设计小组'},{time:'19:30',title:'阅读与摘录',place:'家中'}],
    [{time:'09:00',title:'用户访谈',place:'线上会议'},{time:'15:00',title:'写作时间',place:'个人成长'}],
    [{time:'11:00',title:'项目进度对接',place:'项目空间'},{time:'19:00',title:'晚间运动',place:'附近公园'}],
    [{time:'14:00',title:'本周复盘',place:'个人项目'},{time:'18:30',title:'采购日用品',place:'社区超市'}],
    [{time:'14:00',title:'毕设小组讨论',place:'线上会议'},{time:'18:30',title:'晚间散步',place:'玄武湖畔'}],
    [{time:'10:00',title:'慢慢吃个早餐',place:'家中'},{time:'16:00',title:'整理房间',place:'生活'}],
  ];
  const schedules={};
  calendarDays.forEach((d,i)=>{schedules[d.day]=SCHEDULE_POOL[i%SCHEDULE_POOL.length];});

  /* ===== 待办（真实数据：模块 /api/v1/tasks） ===== */
  let taskList,todoBadge,progressBar,progressText,heroSummary,undatedNote;
  const filterBtns=[];
  let tasks=[],taskLoading=true,taskError='';

  const pad=n=>String(n).padStart(2,'0');
  function fmtMoment(value){
    if(!value)return '';
    const d=new Date(value);
    if(Number.isNaN(d.getTime()))return '';
    const sameDay=d.toDateString()===new Date().toDateString();
    const hm=pad(d.getHours())+':'+pad(d.getMinutes());
    return sameDay?'今天 '+hm:(d.getMonth()+1)+'/'+d.getDate()+' '+hm;
  }
  const dayKey=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  const todayKey=()=>dayKey(new Date());
  function dateKeyOf(iso){
    if(!iso)return null;
    const d=new Date(iso);
    if(Number.isNaN(d.getTime()))return null;
    return dayKey(d);
  }
  function viewOf(t){
    const due=(t.dueTime&&t.dueTime.resolvedValue)||null;
    const start=(t.startTime&&t.startTime.resolvedValue)||null;
    const issues=t.reviewIssues||[];
    const done=t.status==='completed';
    const date=dateKeyOf(due)||dateKeyOf(start);
    return {
      id:t.id,
      title:t.title||'（无标题）',
      done,
      due,start,date,
      overdue:Boolean(!done&&date&&date<todayKey()),
      needsConfirm:Boolean(t.applicability&&t.applicability.status==='needs_confirmation')||issues.length>0,
      requirements:(t.requirements||[]).length,
    };
  }
  /* 首页口径（用户已定）：今天到期 + 逾期未完成；无日期的任务不上首页。 */
  function todayTasks(){
    const key=todayKey();
    return tasks.filter(t=>t.done?(t.date===key):(t.date===key||t.overdue));
  }
  function undatedOpenCount(){
    return tasks.filter(t=>!t.done&&!t.date).length;
  }
  function updateMetrics(){
    const scoped=todayTasks();
    const open=scoped.filter(t=>!t.done).length,done=scoped.length-open;
    todoBadge.textContent=open;
    heroSummary.textContent=scoped.length?`今天 ${open} 件待办，已完成 ${done} 件。`:'今天没有到期的待办，导入通知试试。';
    progressText.textContent=`今日已完成 ${done} / ${scoped.length}`;
    progressBar.style.width=(scoped.length?Math.round(done/scoped.length*100):0)+'%';
    if(undatedNote){
      const n=undatedOpenCount();
      undatedNote.textContent=n?`另有 ${n} 条未安排日期的待办 · 去清单安排`:'';
      undatedNote.hidden=!n;
    }
  }
  function renderTasks(){
    const scoped=todayTasks();
    const filtered=scoped.filter(t=>state.filter==='active'?!t.done:state.filter==='done'?t.done:true);
    filterBtns.forEach(b=>{const on=b.dataset.filter===state.filter;b.className='rounded-md px-2.5 py-1 text-[10.5px] font-medium transition-colors '+(on?'bg-white text-[#244C40] shadow-sm':'text-[#7C8780] hover:text-[#244C40]');b.setAttribute('aria-pressed',on);});
    if(taskLoading){
      taskList.replaceChildren(el('p',{class:'py-6 text-center text-[11px] text-[#A0A7A1]'},'正在读取待办…'));
    }else if(taskError){
      const retry=button('重试',()=>{taskLoading=true;renderTasks();loadTasks();},'',{class:'wb-quiet'});
      taskList.replaceChildren(el('div',{class:'flex h-full min-h-[118px] flex-col items-center justify-center text-center'},
        el('p',{class:'text-[11.5px] font-medium text-[#B4543B]'},'待办读取失败'),
        el('p',{class:'mt-1 text-[9.5px] text-[#A0A7A1]'},taskError),el('div',{class:'mt-2'},retry)));
    }else if(!filtered.length){
      const txt=state.filter==='done'?'今天还没有完成的待办':state.filter==='active'?'今天的待办已经清空':'今天还没有到期的待办';
      const go=button('去导入通知',()=>context.navigate('/tasks/import'),'',{class:'wb-quiet'});
      taskList.replaceChildren(el('div',{class:'flex h-full min-h-[118px] flex-col items-center justify-center text-center'},
        el('span',{class:'grid h-9 w-9 place-items-center rounded-full bg-[#F0F3EC] text-[#7F9486]'},icon('checklist',19)),
        el('p',{class:'mt-2 text-[11.5px] font-medium text-[#627168]'},txt),
        el('p',{class:'mt-1 text-[9.5px] text-[#A0A7A1]'},'截图或粘贴文字，工作台会帮你整理成待办。'),
        el('div',{class:'mt-2.5'},go)));
    }else{
      taskList.replaceChildren(...filtered.slice(0,6).map(task=>{
        const tone=task.done?'border-[#EFEDE5]':'border-[#EFEDE5] hover:bg-[#F7F7F2]';
        const titleTone=task.done?'text-[#A0A6A1] line-through decoration-[#C2C6C2]':'text-[#2D3932] group-hover:text-[#244C40]';
        const badge=task.needsConfirm&&!task.done?el('span',{class:'ml-1 shrink-0 rounded-md bg-[#F6EAD3] px-1.5 py-0.5 text-[8.5px] font-semibold text-[#8A5B2B]'},'待确认'):null;
        const mark=el('button',{type:'button','aria-label':(task.done?'标记为未完成：':'标记为完成：')+task.title,class:'grid h-6 w-6 shrink-0 place-items-center rounded-full text-[#9AA49E] transition-colors hover:bg-[#EAF0E8] hover:text-[#244C40]'},icon(task.done?'check-circle':'circle',18));
        mark.addEventListener('click',()=>toggleTask(task));
        const titleBtn=el('button',{type:'button',class:'truncate text-left text-[12.5px] font-medium '+titleTone},task.title);
        titleBtn.addEventListener('click',()=>context.navigate('/tasks'));
        const when=(task.overdue?'已逾期 · ':'')+(task.due?('截止 '+fmtMoment(task.due)):task.start?('开始 '+fmtMoment(task.start)):'未排期');
        const meta=el('div',{class:'mt-0.5 flex items-center gap-1.5 text-[9.5px] text-[#949C97]'},
          el('span',{class:'truncate'},when),
          task.requirements?el('span',{},'·'):null,
          task.requirements?el('span',{class:'shrink-0'},task.requirements+' 条要求'):null);
        const info=el('div',{class:'min-w-0 flex-1'},el('div',{class:'flex items-center gap-1.5'},titleBtn,badge),meta);
        return el('div',{class:'group flex items-center gap-2.5 rounded-lg border-b px-2 py-1.5 transition-colors '+tone},mark,info);
      }));
    }
    updateMetrics();
  }
  async function loadTasks(){
    try{const data=await context.api.request('/tasks?status=all');tasks=(data.tasks||[]).map(viewOf);taskLoading=false;taskError='';}
    catch(e){taskLoading=false;taskError=e.message||'无法连接待办模块';}
    renderTasks();
  }
  async function toggleTask(task){
    const next=task.done?'open':'completed';
    try{
      const body=next==='completed'?{status:'completed'}:{status:'open'};
      await context.api.request('/tasks/'+encodeURIComponent(task.id),{method:'PATCH',body});
      toast(next==='completed'?'已完成：'+task.title:'已恢复：'+task.title);
      await loadTasks();
    }catch(e){toast(e.message||'操作失败',true);}
  }

  /* 梗词 */
  let memeWord,memeDesc,memeList;
  const memeModal=mkOverlay('memeModal',[
    el('div',{class:'flex items-start justify-between gap-4'},
      el('span',{class:'rounded-full border border-[#EADAC7] bg-[#F8EBDC] px-2.5 py-1 text-[9.5px] font-medium text-[#976C4D]'},'网络梗词小报'),
      el('button',{type:'button','aria-label':'关闭',class:'grid h-8 w-8 place-items-center rounded-lg text-[#8B948E] hover:bg-[#F2F2EC] hover:text-[#244C40]',onClick:()=>closeOv(memeModal)},icon('close-circle',19))),
    el('h2',{class:'mt-4 text-[30px] font-semibold tracking-wide text-[#533A2A]',id:'memeModalTitle'},''),
    el('p',{class:'mt-2 text-[13px] leading-6 text-[#7D6656]',id:'memeModalDesc'},''),
    el('div',{class:'mt-4 rounded-xl border border-[#F0E6D9] bg-[#FCF6EE] p-3'},
      el('p',{class:'text-[9.5px] font-medium tracking-wide text-[#A28770]'},'使用场景'),
      el('p',{class:'mt-1.5 text-[11px] leading-5 text-[#776250]',id:'memeModalUsage'},'')),
    el('div',{class:'mt-4 flex justify-end'},
      el('button',{type:'button',class:'rounded-xl bg-[#244C40] px-4 py-2.5 text-[12px] font-medium text-white hover:bg-[#1B3D31]',onClick:()=>closeOv(memeModal)},'知道了'))]);
  function openMemeDetail(w,d,u){
    memeModal.querySelector('#memeModalTitle').textContent=w;
    memeModal.querySelector('#memeModalDesc').textContent=d;
    memeModal.querySelector('#memeModalUsage').textContent=u;
    openOv(memeModal);
  }
  function renderMeme(){
    const m=state.memes[state.memeIndex];
    memeWord.textContent=m.word;memeDesc.textContent=m.desc;
    memeList.replaceChildren(...m.items.map(item=>{
      const b=el('button',{type:'button',class:'group flex min-h-[33px] w-full items-center justify-between gap-3 py-1.5 text-left transition-colors hover:text-[#5B4636]'},
        el('span',{class:'flex min-w-0 items-center gap-2'},el('span',{class:'shrink-0 text-[11px] font-semibold text-[#5D4B3D]'},item.word),el('span',{class:'truncate text-[9.5px] text-[#9B8B7D]'},item.desc)),
        icon('alt-arrow-right',13));
      b.addEventListener('click',()=>openMemeDetail(item.word,item.desc,'在日常聊天里，人们常用「'+item.word+'」形容一种熟悉又微妙的生活状态。'));
      return b;
    }));
  }

  /* 天气 */
  let weatherCity,weatherTemp,weatherCondition,weatherRange,weatherAQI,weatherTip;
  const forecastEls=[];
  const cityModal=mkOverlay('cityModal',[
    el('div',{class:'flex items-start justify-between gap-4'},
      el('div',{},el('h2',{class:'text-[18px] font-semibold text-[#23342B]'},'切换城市'),el('p',{class:'mt-1 text-[11px] text-[#8D958F]'},'选择一个城市，查看今天的天气与出行提示。')),
      el('button',{type:'button','aria-label':'关闭',class:'grid h-8 w-8 place-items-center rounded-lg text-[#8B948E] hover:bg-[#F2F2EC] hover:text-[#244C40]',onClick:()=>closeOv(cityModal)},icon('close-circle',19))),
    el('div',{class:'mt-4 grid grid-cols-2 gap-2.5',id:'cityOptions'}),
    el('p',{class:'mt-4 text-center text-[9.5px] text-[#A0A6A1]'},'天气为演示示例，不构成出行建议')]);
  function renderCityOptions(){
    const box=cityModal.querySelector('#cityOptions');
    box.replaceChildren(...Object.keys(cities).map(name=>{
      const c=cities[name],active=state.city===name;
      const b=el('button',{type:'button',class:'flex items-center justify-between rounded-xl border px-3.5 py-3 text-left transition-colors '+(active?'border-[#244C40] bg-[#EDF3EA]':'border-[#E4E1D6] bg-[#FBFAF6] hover:border-[#B7C9BC] hover:bg-[#F7F9F4]')},
        el('span',{class:'flex items-center gap-2'},el('span',{class:'grid h-7 w-7 place-items-center rounded-lg bg-white/70 text-[#6C8B79]'},icon('cloud-sun',17)),el('span',{class:'text-[12px] font-medium text-[#34453B]'},name)),
        el('span',{class:'text-[13px] font-semibold text-[#4A5E52]'},c.temp+'°'));
      b.addEventListener('click',()=>selectCity(name));
      return b;
    }));
  }
  function selectCity(name){
    const c=cities[name];if(!c)return;state.city=name;
    weatherCity.textContent=name;weatherTemp.textContent=c.temp+'°';weatherCondition.textContent=c.condition;
    weatherRange.textContent=c.low+'°/'+c.high+'°';weatherAQI.textContent=c.aqi;weatherTip.textContent=c.tip;
    forecastEls.forEach((el,i)=>el.textContent=c.forecast[i]+'°');
    renderCityOptions();closeOv(cityModal);toast('已切换到 '+name);
  }

  /* 日历 */
  let dayStrip,scheduleDateLabel,scheduleList;
  function renderDayStrip(){
    dayStrip.replaceChildren(...calendarDays.map(item=>{
      const active=item.day===state.selectedDay;
      const b=el('button',{type:'button','aria-label':(now.getMonth()+1)+' 月 '+item.day+' 日 '+item.label,class:'group flex flex-col items-center gap-1 rounded-xl py-1.5 transition-colors '+(active?'bg-[#EFF3ED] text-[#244C40]':'text-[#909A94] hover:bg-[#F4F5F0] hover:text-[#244C40]')},
        el('span',{class:'text-[9px]'},item.label),
        el('span',{class:'flex h-[26px] w-[26px] items-center justify-center rounded-full text-[11px] font-medium transition-colors '+(active?'bg-[#244C40] text-white shadow-sm':'bg-transparent group-hover:bg-[#E8ECE4]')},item.day));
      b.addEventListener('click',()=>{state.selectedDay=item.day;renderDayStrip();renderSchedule();toast('已查看 '+(now.getMonth()+1)+' 月 '+item.day+' 日日程');});
      return b;
    }));
  }
  function renderSchedule(){
    const list=schedules[state.selectedDay]||[];
    scheduleDateLabel.textContent=(now.getMonth()+1)+' 月 '+state.selectedDay+' 日 · '+list.length+' 项日程';
    scheduleList.replaceChildren(...list.map((item,i)=>{
      const dot=el('span',{class:'absolute left-[3px] top-[9px] h-2 w-2 rounded-full border-2 border-[#91AE9D] bg-white'});
      const line=i<list.length-1?el('span',{class:'absolute left-[6px] top-[19px] h-[18px] w-px bg-[#E3E7DE]'}):null;
      const titleRow=el('span',{class:'flex items-center justify-between gap-2'},
        el('span',{class:'truncate text-[11px] font-medium text-[#3F4E44] group-hover:text-[#244C40]'},item.title),
        el('span',{class:'shrink-0 text-[9.5px] font-medium text-[#8B958F]'},item.time));
      const placeRow=el('span',{class:'mt-0.5 block truncate text-[9px] text-[#A0A7A1]'},item.place);
      const inner=el('span',{class:'min-w-0 flex-1'},titleRow,placeRow);
      const b=el('button',{type:'button',class:'group relative flex w-full items-start gap-2.5 rounded-lg py-1.5 pl-4 pr-1 text-left transition-colors hover:bg-[#F7F7F2]'},dot,line,inner);
      b.addEventListener('click',()=>toast('已选中日程：'+item.title));
      return b;
    }));
  }

  /* 随手记 */
  let noteDisplay,noteEditor,noteTextarea,noteAddBtn;
  function renderNoteDisplay(){noteDisplay.replaceChildren(...state.noteLines.map(l=>el('p',{class:'text-[11px] leading-[1.65] text-[#7B6840]'},l)));}
  function enterNoteEdit(){noteDisplay.classList.add('hidden');noteAddBtn.classList.add('hidden');noteEditor.classList.remove('hidden');noteEditor.classList.add('flex');noteTextarea.value=state.noteLines.join('\n');setTimeout(()=>noteTextarea.focus(),40);}
  function exitNoteEdit(){noteEditor.classList.add('hidden');noteEditor.classList.remove('flex');noteDisplay.classList.remove('hidden');noteAddBtn.classList.remove('hidden');}

  /* 全局搜索 */
  const searchInput=document.querySelector('#globalSearch');
  const searchResults=document.querySelector('#searchResults');
  function hideSearch(){searchResults.classList.add('hidden');searchResults.classList.remove('block');}
  function renderSearch(){
    const term=searchInput.value.trim().toLowerCase();
    if(!term){hideSearch();return;}
    const groups=[
      {label:'项目',iconName:'folder-2',items:searchData.projects.filter(x=>x.name.toLowerCase().includes(term)||x.meta.toLowerCase().includes(term))},
      {label:'工具',iconName:'widget-4',items:searchData.tools.filter(x=>x.name.toLowerCase().includes(term)||x.meta.toLowerCase().includes(term))},
      {label:'笔记',iconName:'notebook',items:searchData.notes.filter(x=>x.name.toLowerCase().includes(term)||x.meta.toLowerCase().includes(term))},
    ].filter(g=>g.items.length);
    if(!groups.length){
      searchResults.replaceChildren(el('div',{class:'flex flex-col items-center justify-center px-4 py-8 text-center'},
        el('span',{class:'grid h-9 w-9 place-items-center rounded-full bg-[#F0F3EC] text-[#84988A]'},icon('magnifer',18)),
        el('p',{class:'mt-2 text-[11px] font-medium text-[#607067]'},'没有找到相关内容')));
    }else{
      searchResults.replaceChildren(...groups.map(g=>el('div',{class:'border-b border-[#F0EDE5] py-1.5 last:border-b-0'},
        el('p',{class:'flex items-center gap-1.5 px-3 pb-1 pt-1 text-[9px] font-semibold tracking-[0.12em] text-[#9AA19C]'},icon(g.iconName,12),g.label),
        ...g.items.map(item=>{
          const b=el('button',{type:'button',class:'flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-[#F4F6F0]'},
            el('span',{class:'min-w-0 truncate text-[11px] font-medium text-[#3F4E44]'},item.name),
            el('span',{class:'shrink-0 text-[9px] text-[#A0A7A1]'},item.meta));
          b.addEventListener('click',()=>{toast('已打开「'+item.name+'」');hideSearch();});
          return b;
        }))));
    }
    searchResults.classList.remove('hidden');searchResults.classList.add('block');
  }
  searchInput.addEventListener('input',renderSearch);
  searchInput.addEventListener('focus',()=>{if(searchInput.value.trim())renderSearch();});
  document.addEventListener('keydown',e=>{
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();searchInput.focus();searchInput.select();}
    if(e.key==='Escape'){hideSearch();closeOv(cityModal);closeOv(memeModal);}
  });
  document.addEventListener('click',e=>{if(!document.querySelector('#searchWrap').contains(e.target))hideSearch();});

  /* 常用入口 */
  const entries=el('section',{class:'flex flex-col rounded-2xl border border-[#E3E0D5] bg-white p-4 shadow-[0_4px_18px_rgba(36,76,64,0.04)]'});
  function draw(modules){
    const avail=modules.filter(m=>m.status==='available');
    const needsSettings=avail.filter(m=>(m.summary||{}).availability==='尚未配置扫描目录');
    const grid=el('div',{class:'mt-3 grid min-h-0 flex-1 grid-cols-3 gap-2'});
    for(const m of avail){
      grid.append(el('button',{type:'button','aria-label':'进入'+m.title,class:'flex min-h-[52px] flex-col items-center justify-center gap-1.5 rounded-xl border border-[#E4E9E1] bg-[#EEF3ED] text-[#466152] transition-colors hover:border-[#C4D3C8] hover:bg-[#E6EEE5]',onClick:()=>context.navigate(m.route)},
        el('span',{class:'text-[#607F6C]'},icon(m.icon,19)),el('span',{class:'text-[10.5px] font-medium'},m.title)));
    }
    const extra=[{label:'常用工具',icon:'widget-4'},{label:'GitHub',icon:'code'},{label:'AI 助手',icon:'magic-stick'},{label:'学习资料',icon:'book'},{label:'全部收藏',icon:'bookmark'}];
    for(const x of extra.slice(0,Math.max(0,6-avail.length))){
      grid.append(el('button',{type:'button',class:'flex min-h-[52px] flex-col items-center justify-center gap-1.5 rounded-xl border border-[#E4E9E1] bg-[#EEF3ED] text-[#466152] transition-colors hover:border-[#C4D3C8] hover:bg-[#E6EEE5]',onClick:()=>toast('「'+x.label+'」待接入')},
        el('span',{class:'text-[#607F6C]'},icon(x.icon,19)),el('span',{class:'text-[10.5px] font-medium'},x.label)));
    }
    entries.replaceChildren(...[
      el('div',{class:'flex items-center justify-between'},el('h2',{class:'text-[15px] font-semibold tracking-[-0.01em] text-[#2A382F]'},'常用入口'),el('span',{class:'text-[9px] text-[#A0A7A1]'},'6 个入口')),
      grid,
      needsSettings.length?el('div',{class:'mt-2.5 flex flex-wrap items-center gap-2 border-t border-[#EFEDE5] pt-2.5'},
        button('设置扫描目录',()=>context.navigate('/settings'),'',{class:'wb-quiet'})):null,
    ].filter(Boolean));
  }

  /* ===== 组装 ===== */
  const heroCard=el('section',{class:'flex flex-col justify-between rounded-2xl border border-[#E3E0D5] bg-white p-5 shadow-[0_4px_18px_rgba(36,76,64,0.04)]'},
    el('div',{class:'flex items-start justify-between gap-4'},
      el('div',{class:'min-w-0'},
        el('div',{class:'flex flex-wrap items-center gap-2 text-[11px] font-medium tracking-wide text-[#7C867F]'},icon('calendar-date',14),el('span',{},dateLine),el('span',{class:'rounded-full bg-[#F0F2EC] px-2 py-0.5 text-[9px] font-medium tracking-normal text-[#738072]'},'今天')),
        el('h1',{class:'mt-2 text-[26px] font-semibold leading-none tracking-[-0.02em] text-[#1F332A]'},'我的一天'),
        heroSummary=el('p',{class:'mt-2 text-[12.5px] leading-5 text-[#7B857F]'},'')),
      el('button',{type:'button',class:'flex shrink-0 items-center gap-1.5 rounded-xl bg-[#244C40] px-4 py-2.5 text-[12px] font-medium text-white shadow-[0_4px_10px_rgba(36,76,64,0.16)] transition-colors hover:bg-[#1B3D31]',onClick:()=>context.navigate('/tasks/import')},icon('add-circle',16),el('span',{},'新建待办'))),
    (()=>{
      const quick=el('div',{class:'mt-4 flex h-[44px] items-center gap-2 rounded-xl border border-[#DDD9CC] bg-[#FBFAF6] px-3 transition-colors focus-within:border-[#8FAA9A] focus-within:bg-white'});
      const input=el('input',{id:'quickInput',autocomplete:'off',type:'text',placeholder:'有什么想做的，先记下来…',class:'min-w-0 flex-1 bg-transparent text-[12px] text-[#2C3A32] outline-none placeholder:text-[#A1A8A3]'});
      const actions=el('div',{id:'quickActions',class:'hidden shrink-0 items-center gap-1'},
        el('button',{type:'button',class:'rounded-lg bg-[#E7EFE7] px-2 py-1.5 text-[10px] font-medium text-[#3F5E4C] hover:bg-[#DCE9DE]',onClick:()=>saveQuick('todo')},'存为待办'),
        el('button',{type:'button',class:'rounded-lg bg-[#F8EFD7] px-2 py-1.5 text-[10px] font-medium text-[#725D32] hover:bg-[#F3E5C4]',onClick:()=>saveQuick('note')},'存为笔记'));
      function saveQuick(type){
        const v=input.value.trim();if(!v){input.focus();return;}
        if(type==='todo'){
          /* 待办只能由模块的导入链路创建，这里把文本带过去并在导入页预填。 */
          try{sessionStorage.setItem('wb.pendingTodoText',v);}catch(e){/* 隐私模式忽略 */}
          input.value='';updateQuick();
          context.navigate('/tasks/import');
          toast('已带到导入页，确认后保存');
          return;
        }
        state.noteLines.push(v);renderNoteDisplay();toast('已存入随手记');
        input.value='';updateQuick();
      }
      function updateQuick(){const has=input.value.trim().length>0;actions.classList.toggle('hidden',!has);actions.classList.toggle('flex',has);}
      input.addEventListener('input',updateQuick);
      input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();saveQuick('todo');}});
      quick.append(icon('add-circle',17),input,actions);
      return quick;
    })());

  const weatherCard=el('section',{class:'relative flex flex-col justify-between overflow-hidden rounded-2xl border border-[#C7DADF] bg-[#DCEFF4] p-4 text-[#25464B] shadow-[0_4px_18px_rgba(58,104,112,0.08)]'},
    (()=>{const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('aria-hidden','true');svg.setAttribute('class','pointer-events-none absolute inset-0 h-full w-full');svg.setAttribute('preserveAspectRatio','xMidYMax slice');svg.setAttribute('viewBox','0 0 700 280');
      svg.innerHTML='<defs><linearGradient id="weatherSky" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#CFE8F0"/><stop offset="62%" stop-color="#E5F2EF"/><stop offset="100%" stop-color="#D7E8E4"/></linearGradient><linearGradient id="weatherLake" x1="0" x2="1" y1="0" y2="1"><stop offset="0%" stop-color="#BEDDE0"/><stop offset="100%" stop-color="#A7CDD2"/></linearGradient></defs><rect fill="url(#weatherSky)" height="280" width="700"/><circle cx="568" cy="62" fill="#F5D98A" opacity="0.22" r="44"/><circle cx="568" cy="62" fill="#F3CF72" r="26"/><g fill="#FFFFFF" opacity="0.82"><ellipse cx="470" cy="76" rx="33" ry="13"/><ellipse cx="498" cy="70" rx="22" ry="11"/><ellipse cx="442" cy="71" rx="17" ry="9"/></g><path d="M0 176 C90 140 146 158 202 168 C280 181 318 143 390 158 C458 172 520 150 700 166 L700 280 L0 280 Z" fill="#AECDBB" opacity="0.58"/><path d="M0 196 C92 169 172 186 250 192 C338 198 386 169 470 183 C548 196 620 186 700 189 L700 280 L0 280 Z" fill="#91B8A9" opacity="0.5"/><rect fill="url(#weatherLake)" height="78" width="700" y="202"/><g opacity="0.45" stroke="#FFFFFF" stroke-linecap="round" stroke-width="1.5"><path d="M30 224 C58 220 76 228 104 224"/><path d="M430 219 C460 215 482 224 512 218"/><path d="M520 246 C550 242 580 251 614 244"/><path d="M150 255 C176 251 198 259 226 254"/></g><g fill="#FFFFFF" opacity="0.6"><circle cx="623" cy="44" r="2"/><circle cx="640" cy="58" r="1.2"/></g>';return svg;})(),
    el('div',{class:'relative z-10 flex items-start justify-between gap-3'},
      (()=>{const b=el('button',{type:'button','aria-label':'切换天气城市',class:'flex items-center gap-1.5 rounded-full border border-white/60 bg-white/60 px-2.5 py-1 text-[11px] font-medium text-[#25464B] transition-colors hover:bg-white/90'},icon('map-point',13),weatherCity=el('span',{},state.city),icon('alt-arrow-down',12));b.addEventListener('click',()=>{renderCityOptions();openOv(cityModal);});return b;})(),
      weatherAQI=el('span',{class:'rounded-full border border-white/50 bg-white/[0.45] px-2.5 py-1 text-[9px] font-medium text-[#376066]'},'空气优')),
    el('div',{class:'relative z-10 mt-1'},
      el('div',{class:'flex items-start gap-2'},
        weatherTemp=el('span',{class:'text-[42px] font-semibold leading-none tracking-[-0.06em]'},'23°'),
        el('div',{class:'pt-1'},weatherCondition=el('p',{class:'text-[12px] font-medium'},'晴间多云'),el('p',{class:'mt-1 text-[10px] text-[#56777B]'},weatherRange=el('span',{},'18°/25°'),el('span',{class:'mx-1.5'},'·'),weatherTip=el('span',{},'适合出门走走'))))),
    (()=>{const box=el('div',{class:'relative z-10 mt-3 grid grid-cols-4 gap-1.5 rounded-xl border border-white/[0.45] bg-white/[0.55] p-1.5'});
      [['现在',23],['12 时',25],['15 时',24],['18 时',21]].forEach(([label,temp],i)=>{
        forecastEls.push(el('span',{class:'text-[12px] font-semibold'},temp+'°'));
        box.append(el('div',{class:'flex flex-col items-center gap-0.5 rounded-lg px-1 py-1 text-[#31555A] '+(i===0?'bg-white/[0.55]':'')},el('span',{class:'text-[9px] opacity-75'},label),forecastEls[i]));
      });
      return box;})());

  const todoCard=el('section',{class:'flex flex-col rounded-2xl border border-[#E3E0D5] bg-white p-4 shadow-[0_4px_18px_rgba(36,76,64,0.04)] xl:p-5',id:'todoCard'},
    el('div',{class:'flex flex-wrap items-center justify-between gap-2.5'},
      el('div',{class:'flex items-center gap-2'},el('h2',{class:'text-[16px] font-semibold tracking-[-0.01em] text-[#25362D]'},'今日待办'),todoBadge=el('span',{class:'grid h-[20px] min-w-[20px] place-items-center rounded-full bg-[#E8EFE7] px-1.5 text-[10px] font-semibold text-[#466453]'},'0')),
      el('div',{class:'flex items-center gap-2'},
        (()=>{const g=el('div',{class:'flex items-center gap-0.5 rounded-lg bg-[#F4F3ED] p-0.5',role:'group','aria-label':'任务筛选'});
          [['all','全部'],['active','进行中'],['done','已完成']].forEach(([k,label])=>{
            const b=el('button',{type:'button','data-filter':k,class:'rounded-md px-2.5 py-1 text-[10.5px] font-medium text-[#7C8780] transition-colors hover:text-[#244C40]'},label);
            b.addEventListener('click',()=>{state.filter=k;renderTasks();});
            filterBtns.push(b);g.append(b);
          });
          return g;})(),
        )),
    taskList=el('div',{class:'mt-2.5 min-h-0 flex-1 overflow-y-auto overscroll-contain'}),
    el('div',{class:'mt-2 border-t border-[#EFEDE5] pt-2.5'},
      el('div',{class:'flex items-center gap-3'},
        el('div',{class:'h-1.5 flex-1 overflow-hidden rounded-full bg-[#ECEDE6]'},progressBar=el('div',{class:'h-full rounded-full bg-[#8FAD9C] transition-[width] duration-300'})),
        progressText=el('span',{class:'shrink-0 text-[10px] text-[#87918B]'},''))),
      undatedNote=el('button',{type:'button',hidden:true,class:'mt-2 w-full rounded-lg bg-[#F7F6F1] px-2.5 py-1.5 text-left text-[10px] text-[#6B7A70] hover:bg-[#F0EEE7]',onClick:()=>context.navigate('/tasks')},''));

  const memeCard=el('section',{class:'flex flex-col rounded-2xl border border-[#E5DDD1] bg-white p-4 shadow-[0_4px_18px_rgba(82,57,36,0.04)] xl:p-5'},
    el('div',{class:'flex items-center justify-between gap-2'},
      el('div',{class:'flex items-center gap-2'},el('h2',{class:'text-[16px] font-semibold tracking-[-0.01em] text-[#2A352F]'},'网络梗词小报'),el('span',{class:'rounded-full border border-[#E8DCCB] bg-[#FAF4EC] px-2 py-0.5 text-[9px] text-[#9A7A5D]'},'示例')),
      el('button',{type:'button',class:'flex items-center gap-1 rounded-lg px-2 py-1 text-[10.5px] text-[#85796C] transition-colors hover:bg-[#F8F2E9] hover:text-[#5B4636]',onClick:()=>{state.memeIndex=(state.memeIndex+1)%state.memes.length;renderMeme();toast('换了一批新鲜热梗');}},icon('refresh',14),el('span',{},'换一批'))),
    (()=>{const b=el('button',{type:'button','aria-label':'查看今日热梗解释',class:'group mt-2.5 flex h-[96px] w-full shrink-0 items-stretch justify-between gap-3 overflow-hidden rounded-xl border border-[#ECDCC9] bg-[#F7E8D8] p-3.5 text-left transition-colors hover:bg-[#F5E2CF]'},
      el('div',{class:'min-w-0'},
        el('span',{class:'inline-flex rounded-md bg-white/60 px-2 py-0.5 text-[9px] font-medium text-[#9A6A4A]'},'今日解梗'),
        memeWord=el('p',{class:'mt-1.5 text-[21px] font-semibold leading-none tracking-wide text-[#5A3D2D]'},''),
        memeDesc=el('p',{class:'mt-1.5 line-clamp-2 max-h-[30px] overflow-hidden text-[10.5px] leading-[1.5] text-[#8D6D58]'},'')),
      el('div',{class:'relative flex h-[68px] w-[78px] shrink-0 items-center justify-center rounded-2xl border border-[#DFC5AC] bg-[#FBF2E8] text-[#A37A5C]'},
        el('span',{class:'absolute left-2 top-2 h-1.5 w-1.5 rounded-full bg-[#D5A77F]'}),
        icon('cup-hot',34),
        el('span',{class:'absolute bottom-2 right-3 text-[#8D735F]'},icon('bag',26)),
        el('span',{class:'absolute bottom-3 left-3 h-px w-7 bg-[#D8BFA8]'})));
      b.addEventListener('click',()=>{const m=state.memes[state.memeIndex];openMemeDetail(m.word,m.desc,m.usage);});
      return b;})(),
    memeList=el('div',{class:'mt-1 flex min-h-0 flex-1 flex-col justify-center divide-y divide-[#F0E9DF]'}),
    el('button',{type:'button',class:'mt-2 flex h-[32px] w-full shrink-0 items-center justify-center gap-1.5 rounded-lg border border-[#E9E1D6] bg-[#FCF9F4] text-[10.5px] font-medium text-[#7D6C5D] transition-colors hover:border-[#D8C8B8] hover:bg-[#F8F2E9]',onClick:()=>toast('正在打开「大家都在聊什么」')},el('span',{},'看看大家都在聊什么'),icon('arrow-up-right',13)));

  const calendarCard=el('section',{class:'flex flex-col rounded-2xl border border-[#E3E0D5] bg-white p-4 shadow-[0_4px_18px_rgba(36,76,64,0.04)]',id:'calendarCard'},
    el('div',{class:'flex items-center justify-between gap-2'},
      el('h2',{class:'text-[15px] font-semibold tracking-[-0.01em] text-[#2A382F]'},'接下来'),
      el('button',{type:'button',class:'flex items-center gap-1 text-[10px] text-[#8A938D] transition-colors hover:text-[#244C40]',onClick:()=>toast('完整日历将在后续页面中开放')},el('span',{},'查看日历'),icon('arrow',13))),
    dayStrip=el('div',{class:'mt-2.5 grid grid-cols-7 gap-0.5'}),
    el('div',{class:'mt-2 flex min-h-0 flex-1 flex-col'},
      el('div',{class:'flex items-center justify-between'},scheduleDateLabel=el('p',{class:'text-[9.5px] font-medium text-[#8D968F]'},''),el('span',{class:'h-px flex-1 bg-[#EFEDE4] ml-2'})),
      scheduleList=el('div',{class:'mt-1 min-h-0 flex-1'})));

  const scratchCard=el('section',{class:'relative flex flex-col overflow-hidden rounded-2xl border border-[#EDE1BD] bg-[#FBF3D9] p-4 shadow-[0_4px_18px_rgba(123,99,46,0.05)]',id:'scratchCard'},
    el('span',{class:'pointer-events-none absolute -right-5 -top-5 h-20 w-20 rounded-full border border-[#EADDAF]','aria-hidden':'true'}),
    el('span',{class:'pointer-events-none absolute bottom-12 right-5 h-1 w-1 rounded-full bg-[#D5C289]','aria-hidden':'true'}),
    el('div',{class:'flex items-center justify-between'},
      el('div',{class:'flex items-center gap-1.5 text-[10px] font-medium tracking-wide text-[#9B8656]'},icon('notebook',14),el('span',{},'随手记')),
      (()=>{const b=el('button',{type:'button','aria-label':'编辑随手记',class:'grid h-7 w-7 place-items-center rounded-lg text-[#9D895D] transition-colors hover:bg-[#F4E8C4] hover:text-[#6D5A32]'},icon('pen-square',16));b.addEventListener('click',enterNoteEdit);return b;})()),
    el('h2',{class:'mt-1.5 text-[15px] font-semibold text-[#5D4D2D]'},'首页想法'),
    noteDisplay=el('div',{class:'mt-2 min-h-0 flex-1 space-y-1 overflow-y-auto'}),
    (()=>{noteEditor=el('div',{class:'mt-2 hidden min-h-0 flex-1 flex-col'});
      noteTextarea=el('textarea',{class:'min-h-[62px] flex-1 resize-none rounded-lg border border-[#E4D4A6] bg-[#FFFDF5] px-2.5 py-2 text-[11px] leading-[1.65] text-[#5F4F2F] outline-none focus:border-[#B7A15F]','aria-label':'随手记内容'});
      noteEditor.append(noteTextarea,el('div',{class:'mt-1.5 flex justify-end gap-1.5'},
        el('button',{type:'button',class:'rounded-md px-2 py-1 text-[10px] text-[#8C7950] transition-colors hover:bg-[#F4E8C4]',onClick:exitNoteEdit},'取消'),
        el('button',{type:'button',class:'rounded-md bg-[#66542E] px-2.5 py-1 text-[10px] font-medium text-white transition-colors hover:bg-[#554525]',onClick:()=>{
          const lines=noteTextarea.value.split('\n').map(l=>l.trim()).filter(Boolean);
          if(!lines.length){toast('写点什么再保存吧');return;}
          state.noteLines=lines;renderNoteDisplay();exitNoteEdit();toast('随手记已更新');
        }},'保存')));
      return noteEditor;})(),
    (()=>{noteAddBtn=el('button',{type:'button',class:'mt-2 flex h-[30px] w-full shrink-0 items-center justify-center gap-1 rounded-lg border border-[#E3D3A6] bg-[#FCF6E3] text-[10px] font-medium text-[#7C693C] transition-colors hover:border-[#D4BF86] hover:bg-[#F9EFD3]'},icon('add-circle',13),el('span',{},'记录一个想法'));
      noteAddBtn.addEventListener('click',enterNoteEdit);return noteAddBtn;})());

  const row1=el('div',{class:'grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]'},heroCard,weatherCard);
  const row2=el('div',{class:'grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]'},todoCard,memeCard);
  const row3=el('div',{class:'grid grid-cols-1 gap-4 lg:grid-cols-3'},entries,calendarCard,scratchCard);
  const foot=el('p',{class:'mt-2.5 pb-0.5 text-center text-[9.5px] tracking-wide text-[#9A9F9A]'},'天气与热梗内容为示例');

  container.replaceChildren(
    el('div',{class:'mx-auto flex min-h-full w-full max-w-[1560px] flex-col px-4 pb-3 pt-4 sm:px-6 lg:px-5 lg:pt-5'},
      el('div',{class:'grid grid-cols-1 gap-4 lg:min-h-[740px] lg:flex-1 lg:grid-rows-[minmax(210px,0.92fr)_minmax(300px,1.22fr)_minmax(222px,0.96fr)]'},row1,row2,row3),
      foot));

  renderTasks();renderMeme();renderDayStrip();renderSchedule();renderNoteDisplay();
  loadTasks();
  draw(context.modules);
  const stopPoll=poll(async()=>{draw((await context.api.bootstrap(context.signal)).modules);await loadTasks();},context.signal);
  return stopPoll;
}
