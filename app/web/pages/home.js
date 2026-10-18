import {el,button,poll} from '../core/dom.js';
import {icon} from '../core/icons.js';

/* 今日总览仪表盘。
   - 待办：接待办模块真实数据（今天到期 + 逾期；无日期不上首页）
   - 天气：接工作台 /api/v1/weather（Open-Meteo，服务端代理，免密钥）
   - 世界快讯：接 /api/v1/world-news（真实 RSS + AI 筛选解读，可换一批）
   - 日程：暂无数据源，先展示空状态
   - 随手记：接 /api/v1/notes 落盘
   - 常用入口：接 bootstrap modules 真实数据 */

const CITY_CACHE_KEY='wb.weather.city';
const cachedCity=(()=>{try{return localStorage.getItem(CITY_CACHE_KEY)||'';}catch(e){return '';}})();
const state={
  filter:'all',selectedDay:18,city:cachedCity||'南京',noteLines:[],
};
const CITY_LIST=['南京','杭州','苏州','上海'];

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
  const dateLine=`${now.getFullYear()} 年 ${now.getMonth()+1} 月 ${now.getDate()} 日 · ${['周日','周一','周二','周三','周四','周五','周六'][now.getDay()]}`;
  const pad=n=>String(n).padStart(2,'0');

  /* ===== 待办（真实数据） ===== */
  let taskList,todoBadge,progressBar,progressText,heroSummary,undatedNote;
  const filterBtns=[];
  let tasks=[],taskLoading=true,taskError='';

  const dayKey=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  const todayKey=()=>dayKey(new Date());
  function dateKeyOf(iso){
    if(!iso)return null;
    const d=new Date(iso);
    if(Number.isNaN(d.getTime()))return null;
    return dayKey(d);
  }
  function fmtMoment(value){
    if(!value)return '';
    const d=new Date(value);
    if(Number.isNaN(d.getTime()))return '';
    const sameDay=d.toDateString()===new Date().toDateString();
    const hm=pad(d.getHours())+':'+pad(d.getMinutes());
    return sameDay?'今天 '+hm:(d.getMonth()+1)+'/'+d.getDate()+' '+hm;
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
  function undatedOpenCount(){return tasks.filter(t=>!t.done&&!t.date).length;}

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
      await context.api.request('/tasks/'+encodeURIComponent(task.id),{method:'PATCH',body:{status:next}});
      toast(next==='completed'?'已完成：'+task.title:'已恢复：'+task.title);
      await loadTasks();
    }catch(e){toast(e.message||'操作失败',true);}
  }

  /* ===== 天气（真实接口） ===== */
  let weatherCityEl,weatherTempEl,weatherConditionEl,weatherRangeEl,weatherHumidityEl,weatherForecastBox,weatherErrorEl;
  let weatherSeq=0;
  const cityModal=mkOverlay('cityModal',[
    el('div',{class:'flex items-start justify-between gap-4'},
      el('div',{},el('h2',{class:'text-[18px] font-semibold text-[#23342B]'},'切换城市'),el('p',{class:'mt-1 text-[11px] text-[#8D958F]'},'输入任意城市名，或点下面的常用城市。')),
      el('button',{type:'button','aria-label':'关闭',class:'grid h-8 w-8 place-items-center rounded-lg text-[#8B948E] hover:bg-[#F2F2EC] hover:text-[#244C40]',onClick:()=>closeOv(cityModal)},icon('close-circle',19))),
    (()=>{
      const row=el('div',{class:'mt-4 flex items-center gap-2'});
      const input=el('input',{id:'cityInput',type:'text',autocomplete:'off',placeholder:'输入城市名，如 成都、武汉',class:'min-w-0 flex-1 rounded-xl border border-[#E1DED2] bg-white px-3 py-2.5 text-[12px] text-[#2C3A32] outline-none transition-colors focus:border-[#8FAA9A]'});
      const go=el('button',{type:'button',class:'shrink-0 rounded-xl bg-[#244C40] px-4 py-2.5 text-[12px] font-medium text-white transition-colors hover:bg-[#1B3D31]'},'查看');
      function submit(){
        const name=input.value.trim();
        if(!name){input.focus();return;}
        selectCity(name);
      }
      go.addEventListener('click',submit);
      input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();submit();}});
      row.append(input,go);
      return row;
    })(),
    el('p',{class:'mt-3 text-[9.5px] text-[#A0A6A1]'},'常用城市'),
    el('div',{class:'mt-1.5 grid grid-cols-4 gap-2',id:'cityOptions'}),
    el('p',{class:'mt-3 text-center text-[9.5px] text-[#A0A6A1]'},'天气数据来自 Open-Meteo，实时更新，仅供参考')]);
  function renderCityOptions(){
    const box=cityModal.querySelector('#cityOptions');
    box.replaceChildren(...CITY_LIST.map(name=>{
      const active=state.city===name;
      const b=el('button',{type:'button',class:'flex items-center justify-center rounded-xl border px-2 py-2.5 transition-colors '+(active?'border-[#244C40] bg-[#EDF3EA]':'border-[#E4E1D6] bg-[#FBFAF6] hover:border-[#B7C9BC] hover:bg-[#F7F9F4]')},
        el('span',{class:'flex items-center gap-1.5'},el('span',{class:'text-[#6C8B79]'},icon('cloud-sun',15)),el('span',{class:'text-[11.5px] font-medium text-[#34453B]'},name)));
      b.addEventListener('click',()=>selectCity(name));
      return b;
    }));
  }
  async function loadPreferences(){
    try{
      const data=await context.api.request('/preferences');
      const city=(data&&data.city||'').trim();
      if(city){
        state.city=city;
        weatherCityEl.textContent=city;
        try{localStorage.setItem(CITY_CACHE_KEY,city);}catch(e){}
      }
    }catch(e){/* 偏好读取失败时沿用本地缓存/默认城市 */}
    loadWeather(state.city);
  }
  async function loadWeather(city){
    const seq=++weatherSeq;
    weatherErrorEl.hidden=true;
    weatherErrorEl.textContent='';
    weatherConditionEl.textContent='读取中…';
    try{
      const data=await context.api.request('/weather?city='+encodeURIComponent(city));
      if(seq!==weatherSeq)return;
      state.city=data.city||city;
      weatherCityEl.textContent=state.city;
      try{localStorage.setItem(CITY_CACHE_KEY,state.city);}catch(e){}
      context.api.request('/preferences',{method:'PUT',body:{city:state.city}}).catch(()=>{});
      weatherTempEl.textContent=data.temperature+'°';
      weatherConditionEl.textContent=data.condition||'—';
      weatherRangeEl.textContent=(data.low??'—')+'°/ '+(data.high??'—')+'°';
      weatherHumidityEl.textContent=data.humidity==null?'—':('湿度 '+data.humidity+'%');
      weatherForecastBox.replaceChildren(...((data.forecast||[]).slice(0,4).map((item,i)=>
        el('div',{class:'flex flex-col items-center gap-0.5 rounded-lg px-1 py-1 text-[#31555A] '+(i===0?'bg-white/[0.55]':'')},
          el('span',{class:'text-[9px] opacity-75'},item.time),
          el('span',{class:'text-[12px] font-semibold'},item.temperature+'°')))));
    }catch(e){
      if(seq!==weatherSeq)return;
      weatherTempEl.textContent='—°';
      weatherConditionEl.textContent='读取失败';
      weatherRangeEl.textContent='—°/ —°';
      weatherHumidityEl.textContent='湿度 —';
      weatherForecastBox.replaceChildren();
      weatherErrorEl.textContent=(e.message||'天气服务暂时不可用')+'（Open-Meteo 连接失败）';
      weatherErrorEl.hidden=false;
    }
  }
  function selectCity(name){
    const city=(name||'').trim();
    if(!city)return;
    closeOv(cityModal);
    state.city=city;
    weatherCityEl.textContent=city;
    renderCityOptions();
    loadWeather(city);
  }

  /* ===== 世界快讯（真实 RSS + AI 筛选解读） ===== */
  let newsListEl,newsMetaEl,newsRefreshBtn,newsErrorEl,newsLoading=false;
  const NEWS_FALLBACK='暂时无法获取新闻源，请稍后再试。';
  function newsItemNode(item){
    const tag=el('span',{class:'shrink-0 rounded-md bg-[#EAF0E8] px-1.5 py-0.5 text-[8.5px] font-medium text-[#4C6B57]'},item.category||'资讯');
    const title=el('a',{href:item.url,target:'_blank',rel:'noopener noreferrer',class:'min-w-0 flex-1 truncate text-[11.5px] font-medium text-[#2F4036] transition-colors hover:text-[#244C40] hover:underline'},item.title);
    const meta=el('p',{class:'mt-px truncate text-[9px] text-[#A0A7A1]'},item.source+(item.publishedAt?(' · '+fmtNewsTime(item.publishedAt)):''));
    const rows=[el('div',{class:'flex items-start gap-1.5'},tag,title),meta];
    if(item.summary)rows.push(el('p',{class:'mt-px line-clamp-2 text-[10px] leading-[13px] text-[#7A6A55]'},item.summary));
    return el('div',{class:'rounded-lg border-b border-[#F0EDE5] px-1 py-1 last:border-b-0'},...rows);
  }
  function fmtNewsTime(value){
    try{
      const d=new Date(value);
      if(Number.isNaN(d.getTime()))return value;
      const sameDay=d.toDateString()===new Date().toDateString();
      return sameDay?('今天 '+pad(d.getHours())+':'+pad(d.getMinutes())):((d.getMonth()+1)+'/'+d.getDate());
    }catch(e){return value;}
  }
  async function loadNews(refresh){
    if(newsLoading)return;
    newsLoading=true;
    newsRefreshBtn.disabled=true;
    newsErrorEl.hidden=true;
    newsMetaEl.textContent='正在获取全球新闻…';
    newsListEl.replaceChildren(el('p',{class:'py-6 text-center text-[10.5px] text-[#A0A7A1]'},'正在读取新闻源…'));
    try{
      const data=await context.api.request('/world-news'+(refresh?'?refresh=1':''));
      const items=data.items||[];
      newsListEl.replaceChildren(...items.map(newsItemNode));
      const stamp=data.aiUsed?'AI 精选 · 实时抓取':'最新标题 · 实时抓取';
      newsMetaEl.textContent=stamp+'（'+(data.sourceCount||0)+' 个来源 / '+(data.totalFetched||items.length)+' 条）';
    }catch(e){
      newsListEl.replaceChildren();
      newsErrorEl.textContent=e.message||NEWS_FALLBACK;
      newsErrorEl.hidden=false;
      newsMetaEl.textContent='世界快讯';
    }finally{
      newsLoading=false;
      newsRefreshBtn.disabled=false;
    }
  }

  /* ===== 日程（暂无数据源，空状态） ===== */
  let dayStrip,scheduleDateLabel,scheduleList;
  const calendarDays=[];
  for(let d=now.getDate()-6;d<=now.getDate();d++){
    calendarDays.push({day:d,label:['周日','周一','周二','周三','周四','周五','周六'][new Date(now.getFullYear(),now.getMonth(),d).getDay()]});
  }
  state.selectedDay=now.getDate();
  function renderDayStrip(){
    dayStrip.replaceChildren(...calendarDays.map(item=>{
      const active=item.day===state.selectedDay;
      const b=el('button',{type:'button','aria-label':(now.getMonth()+1)+' 月 '+item.day+' 日 '+item.label,class:'group flex flex-col items-center gap-1 rounded-xl py-1.5 transition-colors '+(active?'bg-[#EFF3ED] text-[#244C40]':'text-[#909A94] hover:bg-[#F4F5F0] hover:text-[#244C40]')},
        el('span',{class:'text-[9px]'},item.label),
        el('span',{class:'flex h-[26px] w-[26px] items-center justify-center rounded-full text-[11px] font-medium transition-colors '+(active?'bg-[#244C40] text-white shadow-sm':'bg-transparent group-hover:bg-[#E8ECE4]')},item.day));
      b.addEventListener('click',()=>{state.selectedDay=item.day;renderDayStrip();renderSchedule();});
      return b;
    }));
  }
  function renderSchedule(){
    scheduleDateLabel.textContent=(now.getMonth()+1)+' 月 '+state.selectedDay+' 日 · 暂无日程';
    scheduleList.replaceChildren(el('div',{class:'flex h-full min-h-[86px] flex-col items-center justify-center text-center'},
      el('span',{class:'grid h-8 w-8 place-items-center rounded-full bg-[#F0F3EC] text-[#84988A]'},icon('calendar',16)),
      el('p',{class:'mt-1.5 text-[10.5px] font-medium text-[#7E8C84]'},'日程功能尚未接入'),
      el('p',{class:'mt-0.5 text-[9px] text-[#A0A7A1]'},'待办清单页的月历可以先看安排')));
  }

  /* ===== 随手记（落盘） ===== */
  let noteDisplay,noteEditor,noteTextarea,noteAddBtn,noteSaving=false;
  function renderNoteDisplay(){
    if(!state.noteLines.length){
      noteDisplay.replaceChildren(el('p',{class:'text-[10.5px] leading-[1.65] text-[#9A8558]'},'还没有随手记。点右下角记一条。'));
      return;
    }
    noteDisplay.replaceChildren(...state.noteLines.map(l=>el('p',{class:'text-[11px] leading-[1.65] text-[#7B6840]'},l)));
  }
  async function loadNotes(){
    try{const data=await context.api.request('/notes');state.noteLines=(data.lines||[]).slice();}
    catch(e){state.noteLines=[];}
    renderNoteDisplay();
  }
  async function saveNotes(lines){
    if(noteSaving)return;
    noteSaving=true;
    try{
      const data=await context.api.request('/notes',{method:'PUT',body:{lines}});
      state.noteLines=(data.lines||[]).slice();
      renderNoteDisplay();
      exitNoteEdit();
      toast('随手记已保存');
    }catch(e){toast(e.message||'保存失败',true);}
    finally{noteSaving=false;}
  }
  function enterNoteEdit(){
    noteDisplay.classList.add('hidden');noteAddBtn.classList.add('hidden');
    noteEditor.classList.remove('hidden');noteEditor.classList.add('flex');
    noteTextarea.value=state.noteLines.join('\n');
    setTimeout(()=>noteTextarea.focus(),40);
  }
  function exitNoteEdit(){
    noteEditor.classList.add('hidden');noteEditor.classList.remove('flex');
    noteDisplay.classList.remove('hidden');noteAddBtn.classList.remove('hidden');
  }

  /* ===== 全局搜索（真实数据：项目 / 待办 / 长期任务） ===== */
  const searchInput=document.querySelector('#globalSearch');
  const searchResults=document.querySelector('#searchResults');
  const searchGroupMeta={projects:{label:'项目',iconName:'folder-2'},tasks:{label:'待办',iconName:'checklist'},goals:{label:'长期任务',iconName:'star'}};
  let searchSeq=0,searchTimer=null;
  function hideSearch(){searchResults.classList.add('hidden');searchResults.classList.remove('block');}
  function showSearch(){searchResults.classList.remove('hidden');searchResults.classList.add('block');}
  function searchMessage(title,detail){
    searchResults.replaceChildren(el('div',{class:'flex flex-col items-center justify-center px-4 py-8 text-center'},
      el('span',{class:'grid h-9 w-9 place-items-center rounded-full bg-[#F0F3EC] text-[#84988A]'},icon('magnifer',18)),
      el('p',{class:'mt-2 text-[11px] font-medium text-[#607067]'},title),
      detail?el('p',{class:'mt-1 text-[9.5px] text-[#A0A7A1]'},detail):null));
    showSearch();
  }
  function searchGroupNode(group){
    const meta=searchGroupMeta[group.key]||{label:group.label||group.key,iconName:'magnifer'};
    const rows=group.items.map(item=>{
      const suffix=[item.badge,item.subtitle].filter(Boolean).join(' · ');
      const buttonEl=el('button',{type:'button',class:'flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-[#F4F6F0]'},
        el('span',{class:'min-w-0 flex-1 truncate text-[11px] font-medium text-[#3F4E44]'},item.title),
        el('span',{class:'shrink-0 text-[9px] text-[#A0A7A1]'},suffix));
      buttonEl.addEventListener('click',()=>{hideSearch();searchInput.blur();context.navigate(item.route||'/');});
      return buttonEl;
    });
    const header=el('p',{class:'flex items-center gap-1.5 px-3 pb-1 pt-1 text-[9px] font-semibold tracking-[0.12em] text-[#9AA19C]'},icon(meta.iconName,12),meta.label);
    return el('div',{class:'border-b border-[#F0EDE5] py-1.5 last:border-b-0'},header,...rows);
  }
  async function renderSearch(){
    const term=searchInput.value.trim();
    if(!term){hideSearch();return;}
    const seq=++searchSeq;
    searchMessage('搜索中…','');
    try{
      const data=await context.api.request('/search?q='+encodeURIComponent(term));
      if(seq!==searchSeq)return;
      const groups=(data.groups||[]).filter(group=>group.items&&group.items.length);
      if(!groups.length){
        searchMessage('没有找到「'+term+'」','试试项目名、待办标题或长期任务名称');
        return;
      }
      searchResults.replaceChildren(...groups.map(searchGroupNode));
      showSearch();
    }catch(e){
      if(seq!==searchSeq)return;
      searchMessage('搜索失败',e.message||'请稍后再试');
    }
  }
  searchInput.addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(renderSearch,220);});
  searchInput.addEventListener('focus',()=>{if(searchInput.value.trim())renderSearch();});
  document.addEventListener('keydown',e=>{
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();searchInput.focus();searchInput.select();}
    if(e.key==='Escape'){hideSearch();closeOv(cityModal);}
  });
  document.addEventListener('click',e=>{if(!document.querySelector('#searchWrap')?.contains(e.target))hideSearch();});

  /* ===== 常用入口 ===== */
  const entries=el('section',{class:'flex flex-col rounded-2xl border border-[#E3E0D5] bg-white p-4 shadow-[0_4px_18px_rgba(36,76,64,0.04)]'});
  function draw(modules){
    /* 只展示有导航路由的可用模块；API-only 模块（如首页数据服务）不作为入口。 */
    const avail=modules.filter(m=>m.status==='available'&&m.route);
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
          try{sessionStorage.setItem('wb.pendingTodoText',v);}catch(e){/* 隐私模式忽略 */}
          input.value='';updateQuick();
          context.navigate('/tasks/import');
          toast('已带到导入页，确认后保存');
          return;
        }
        saveNotes([...state.noteLines,v]);
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
      (()=>{const b=el('button',{type:'button','aria-label':'切换天气城市',class:'flex items-center gap-1.5 rounded-full border border-white/60 bg-white/60 px-2.5 py-1 text-[11px] font-medium text-[#25464B] transition-colors hover:bg-white/90'},icon('map-point',13),weatherCityEl=el('span',{},state.city),icon('alt-arrow-down',12));b.addEventListener('click',()=>{renderCityOptions();openOv(cityModal);});return b;})(),
      weatherHumidityEl=el('span',{class:'rounded-full border border-white/50 bg-white/[0.45] px-2.5 py-1 text-[9px] font-medium text-[#376066]'},'湿度 —')),
    el('div',{class:'relative z-10 mt-1'},
      el('div',{class:'flex items-start gap-2'},
        weatherTempEl=el('span',{class:'text-[42px] font-semibold leading-none tracking-[-0.06em]'},'—°'),
        el('div',{class:'pt-1'},
          weatherConditionEl=el('p',{class:'text-[12px] font-medium'},'读取中…'),
          el('p',{class:'mt-1 text-[10px] text-[#56777B]'},weatherRangeEl=el('span',{},'—°/ —°')),
          weatherErrorEl=el('p',{class:'mt-0.5 hidden text-[9.5px] text-[#B4543B]','role':'alert'})))),
    weatherForecastBox=el('div',{class:'relative z-10 mt-3 grid grid-cols-4 gap-1.5 rounded-xl border border-white/[0.45] bg-white/[0.55] p-1.5'}));

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
          return g;})())),
    taskList=el('div',{class:'mt-2.5 min-h-0 flex-1 overflow-y-auto overscroll-contain'}),
    el('div',{class:'mt-2 border-t border-[#EFEDE5] pt-2.5'},
      el('div',{class:'flex items-center gap-3'},
        el('div',{class:'h-1.5 flex-1 overflow-hidden rounded-full bg-[#ECEDE6]'},progressBar=el('div',{class:'h-full rounded-full bg-[#8FAD9C] transition-[width] duration-300'})),
        progressText=el('span',{class:'shrink-0 text-[10px] text-[#87918B]'},''))),
    undatedNote=el('button',{type:'button',hidden:true,class:'mt-2 w-full rounded-lg bg-[#F7F6F1] px-2.5 py-1.5 text-left text-[10px] text-[#6B7A70] hover:bg-[#F0EEE7]',onClick:()=>context.navigate('/tasks')},''));

  const newsCard=el('section',{class:'flex min-h-0 max-h-[440px] flex-col rounded-2xl border border-[#E5DDD1] bg-white p-4 shadow-[0_4px_18px_rgba(82,57,36,0.04)] xl:p-5',id:'newsCard'},
    el('div',{class:'flex items-center justify-between gap-2'},
      el('div',{class:'flex items-center gap-2'},
        el('h2',{class:'text-[16px] font-semibold tracking-[-0.01em] text-[#2A352F]'},'世界快讯'),
        el('span',{class:'rounded-full border border-[#D8E4DA] bg-[#EDF3EA] px-2 py-0.5 text-[9px] text-[#4C6B57]'},'AI 精选')),
      (()=>{const b=el('button',{type:'button',class:'flex items-center gap-1 rounded-lg px-2 py-1 text-[10.5px] text-[#85796C] transition-colors hover:bg-[#F8F2E9] hover:text-[#5B4636]'},icon('refresh',14),el('span',{},'换一批'));
        b.addEventListener('click',()=>loadNews(true));
        newsRefreshBtn=b;return b;})()),
    newsListEl=el('div',{class:'mt-2 min-h-0 max-h-[300px] flex-1 overflow-y-auto overscroll-contain rounded-xl border border-[#ECE8DE] bg-[#FBFAF6] px-2.5 py-1'}),
    newsErrorEl=el('p',{class:'mt-2 hidden text-[10px] text-[#B4543B]','role':'alert'},''),
    el('p',{class:'mt-2 text-[9px] leading-4 tracking-wide text-[#A0A7A1]'},
      newsMetaEl=el('span',{},'世界快讯'),
      el('span',{},' · 新闻来自公开 RSS，AI 只做筛选与解读，点击标题看原文')));

  const calendarCard=el('section',{class:'flex flex-col rounded-2xl border border-[#E3E0D5] bg-white p-4 shadow-[0_4px_18px_rgba(36,76,64,0.04)]',id:'calendarCard'},
    el('div',{class:'flex items-center justify-between gap-2'},
      el('h2',{class:'text-[15px] font-semibold tracking-[-0.01em] text-[#2A382F]'},'接下来'),
      el('button',{type:'button',class:'flex items-center gap-1 text-[10px] text-[#8A938D] transition-colors hover:text-[#244C40]',onClick:()=>context.navigate('/tasks')},el('span',{},'打开日历'),icon('arrow',13))),
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
          saveNotes(lines);
        }},'保存')));
      return noteEditor;})(),
    (()=>{noteAddBtn=el('button',{type:'button',class:'mt-2 flex h-[30px] w-full shrink-0 items-center justify-center gap-1 rounded-lg border border-[#E3D3A6] bg-[#FCF6E3] text-[10px] font-medium text-[#7C693C] transition-colors hover:border-[#D4BF86] hover:bg-[#F9EFD3]'},icon('add-circle',13),el('span',{},'记录一个想法'));
      noteAddBtn.addEventListener('click',enterNoteEdit);return noteAddBtn;})());

  const row1=el('div',{class:'grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]'},heroCard,weatherCard);
  const row2=el('div',{class:'grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]'},todoCard,newsCard);
  const row3=el('div',{class:'grid grid-cols-1 gap-4 lg:grid-cols-3'},entries,calendarCard,scratchCard);
  const foot=el('p',{class:'mt-2.5 pb-0.5 text-center text-[9.5px] tracking-wide text-[#9A9F9A]'},'天气来自 Open-Meteo · 段子与规划由 AI 生成，请自行判断');

  container.replaceChildren(
    el('div',{class:'mx-auto flex min-h-full w-full max-w-[1560px] flex-col px-4 pb-3 pt-4 sm:px-6 lg:px-5 lg:pt-5'},
      el('div',{class:'grid grid-cols-1 gap-4 lg:min-h-[740px] lg:flex-1 lg:grid-rows-[minmax(210px,0.92fr)_minmax(300px,1.22fr)_minmax(222px,0.96fr)]'},row1,row2,row3),
      foot));

  renderTasks();renderDayStrip();renderSchedule();renderNoteDisplay();
  loadTasks();loadPreferences();loadNews(false);loadNotes();
  draw(context.modules);
  const stopPoll=poll(async()=>{draw((await context.api.bootstrap(context.signal)).modules);await loadTasks();},context.signal);
  return stopPoll;
}
