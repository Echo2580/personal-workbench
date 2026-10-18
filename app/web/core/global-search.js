import {el} from './dom.js';
import {icon} from './icons.js';

/* The header outlives routed pages. Bind search once for the shell lifetime. */
export function mountGlobalSearch({api,navigate}) {
  const input=document.querySelector('#globalSearch');
  const results=document.querySelector('#searchResults');
  const wrap=document.querySelector('#searchWrap');
  const listeners=new AbortController();
  let timer=null,request=null,sequence=0,disposed=false;
  const groupsMeta={
    projects:{label:'项目',iconName:'folder-2'},
    tasks:{label:'待办',iconName:'checklist'},
    goals:{label:'长期任务',iconName:'star'},
    notes:{label:'随手记',iconName:'notebook'},
  };

  function hide(){results.classList.add('hidden');results.classList.remove('block');input.setAttribute('aria-expanded','false');}
  function show(){results.classList.remove('hidden');results.classList.add('block');input.setAttribute('aria-expanded','true');}
  function cancel(){clearTimeout(timer);request?.abort();request=null;sequence++;}
  function dismiss(){cancel();hide();}
  function message(title,detail){
    results.replaceChildren(el('div',{class:'flex flex-col items-center justify-center px-4 py-8 text-center'},
      el('span',{class:'grid h-9 w-9 place-items-center rounded-full bg-[#F0F3EC] text-[#84988A]'},icon('magnifer',18)),
      el('p',{class:'mt-2 text-[11px] font-medium text-[#607067]'},title),
      detail?el('p',{class:'mt-1 text-[9.5px] text-[#A0A7A1]'},detail):null));
    show();
  }
  function groupNode(group){
    const meta=groupsMeta[group.key]||{label:group.label||group.key,iconName:'magnifer'};
    const rows=group.items.map(item=>{
      const suffix=[item.badge,item.subtitle].filter(Boolean).join(' · ');
      return el('button',{type:'button',title:item.title,class:'flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-[#F4F6F0]',onClick:()=>{
        dismiss();input.blur();navigate(item.route||'/',item.params||{});
      }},el('span',{class:'min-w-0 flex-1 truncate text-[11px] font-medium text-[#3F4E44]'},item.title),
        el('span',{class:'shrink-0 text-[9px] text-[#A0A7A1]'},suffix));
    });
    const header=el('p',{class:'flex items-center gap-1.5 px-3 pb-1 pt-1 text-[9px] font-semibold tracking-[0.12em] text-[#9AA19C]'},icon(meta.iconName,12),meta.label);
    return el('div',{class:'border-b border-[#F0EDE5] py-1.5 last:border-b-0'},header,...rows);
  }
  async function search(){
    const term=input.value.trim();
    if(!term||disposed){dismiss();return;}
    request?.abort();
    const pending=new AbortController(),seq=++sequence;
    request=pending;
    message('搜索中…','');
    try{
      const data=await api.request('/search?q='+encodeURIComponent(term),{signal:pending.signal});
      if(disposed||pending.signal.aborted||seq!==sequence||input.value.trim()!==term)return;
      const groups=(data.groups||[]).filter(group=>group.items&&group.items.length);
      if(!groups.length){message('没有找到「'+term+'」','试试项目名、待办标题、长期任务名称或笔记内容');return;}
      results.replaceChildren(...groups.map(groupNode));show();
    }catch(error){
      if(disposed||pending.signal.aborted||seq!==sequence)return;
      message('搜索失败',error.message||'请稍后再试');
    }finally{if(request===pending)request=null;}
  }
  function schedule(){
    cancel();
    if(!input.value.trim()){hide();return;}
    timer=setTimeout(search,220);
  }
  input.addEventListener('input',schedule,{signal:listeners.signal});
  input.addEventListener('focus',()=>{if(input.value.trim())schedule();},{signal:listeners.signal});
  document.addEventListener('keydown',event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){
      event.preventDefault();input.focus();input.select();
    }
    if(event.key==='Escape')dismiss();
  },{signal:listeners.signal});
  document.addEventListener('click',event=>{if(!wrap.contains(event.target))dismiss();},{signal:listeners.signal});
  window.addEventListener('hashchange',dismiss,{signal:listeners.signal});
  input.setAttribute('aria-controls','searchResults');
  hide();
  return ()=>{if(disposed)return;disposed=true;listeners.abort();dismiss();};
}
