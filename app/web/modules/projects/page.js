import {el,button,heading,field,modal,poll,displayRecipe} from '../../core/dom.js';
import {renderProjectCard} from './card.js';
import {openRecipeEditor} from './recipe-editor.js';
export function mount(container,context){
 const {api,signal,notify}=context;let snapshot,expanded=null,query='',type='all',sort='name',busy=null,lastProjects='';
 const error=el('div',{role:'alert',class:'banner error',hidden:true}),warning=el('div',{class:'banner warning',hidden:true}),subtitle=el('p',{class:'muted'}),scanButton=button('重新扫描',async()=>{try{await api.request('/projects/scan',{method:'POST',signal});await refresh();}catch(e){showError(e);}}),grid=el('div',{class:'projects-grid'}),count=el('p',{class:'muted small result-count'});
 const search=el('input',{type:'search','aria-label':'搜索项目',placeholder:'搜索项目名称或路径',onInput:e=>{query=e.target.value;render();},onKeydown:e=>{if(e.key==='Escape'){e.target.value='';query='';render();}}});
 const filter=el('select',{'aria-label':'项目类型',onChange:e=>{type=e.target.value;render();}},[['all','全部类型'],['python','Python'],['node','Node'],['web','网页'],['go','Go'],['rust','Rust'],['other','其他']].map(([value,label])=>el('option',{value},label)));
 const ordering=el('select',{'aria-label':'排序',onChange:e=>{sort=e.target.value;render();}},el('option',{value:'name'},'按名称排序'),el('option',{value:'recent'},'最近使用'));
 container.replaceChildren(heading('项目启动器','发现、配置和运行你的项目',[button('添加项目',addManual,'primary'),scanButton]),subtitle,error,warning,el('div',{class:'toolbar'},search,filter,ordering),count,grid);
 function showError(e){if(e.name==='AbortError')return;error.textContent=e.message||'请求失败，请重试。';error.hidden=false;}
 async function refresh(){try{snapshot=await api.request('/projects',{signal});subtitle.textContent=`${snapshot.roots.length} 个扫描目录 · ${snapshot.projects.length} 个项目 · ${snapshot.projects.filter(p=>p.active_run).length} 个运行中`;scanButton.disabled=snapshot.is_scanning;scanButton.textContent=snapshot.is_scanning?'正在扫描…':'重新扫描';warning.replaceChildren(...snapshot.warnings.map(w=>el('p',{class:'wrap'},w)));warning.hidden=!snapshot.warnings.length;const current=JSON.stringify(snapshot.projects);if(current!==lastProjects){lastProjects=current;render();}}catch(e){showError(e);throw e;}}
 function render(){if(!snapshot)return;const ps=snapshot.projects.filter(p=>(p.name+' '+p.path).toLowerCase().includes(query.toLowerCase())&&(type==='all'||(type==='other'?!['python','node','web','go','rust'].includes(p.type):p.type===type))).sort((a,b)=>sort==='name'?a.name.localeCompare(b.name,'zh-CN'):(b.last_action_at||'').localeCompare(a.last_action_at||''));count.textContent=`显示 ${ps.length} / ${snapshot.projects.length} 个项目`;grid.replaceChildren(...ps.map(p=>renderProjectCard(p,{online:api.connected,busy,expanded,expand:id=>{expanded=expanded===id?null:id;render();},execute,stop,edit,rename,remove,notify})));
 if(!ps.length)grid.append(el('div',{class:'empty'},el('h2',{},query||type!=='all'?'没有匹配的项目':snapshot.roots.length?'没有发现项目':'尚未配置扫描目录'),el('p',{class:'muted'},query?'调整搜索词或按 Esc 清空搜索。':snapshot.roots.length?'可以手动添加章节目录，或在设置中调整扫描范围。':'先设置扫描目录，工作台会自动发现独立项目。'),button(query?'清空搜索':'设置扫描目录',()=>{if(query){query='';search.value='';render();}else context.navigate('/settings');})));
 const focusId=context.params.get('project');if(focusId&&!query)document.getElementById('project-'+focusId)?.classList.add('highlight');}
 async function stop(p){busy=p.id;render();try{await api.request(`/projects/runs/${p.active_run.id}/stop`,{method:'POST',signal});notify('项目已停止');await refresh();}catch(e){showError(e);}finally{busy=null;render();}}
 async function execute(p,r){busy=p.id;render();error.hidden=true;try{const doc=await api.request(`/projects/${p.id}/recipes`,{signal}),saved=doc.recipes.find(x=>x.id===r.id);if(!saved)throw new Error('配方已删除，请刷新。');const body={recipe_id:r.id,fingerprint:saved.fingerprint};try{await api.request(`/projects/${p.id}/actions`,{method:'POST',body,signal});notify(r.kind==='command'?'已创建受管理运行，请在独立终端操作。':'已请求打开');}catch(e){if(e.code!=='approval_required')throw e;await approve(p,saved,body);}await refresh();}catch(e){showError(e);}finally{busy=null;render();}}
 function approve(p,r,body){return new Promise(resolve=>{let m;const message=el('div',{},el('p',{},'请确认这条配方的实际内容。相同内容下次可直接执行。'),el('dl',{},el('dt',{},'项目'),el('dd',{class:'wrap'},p.name),el('dt',{},'操作类型'),el('dd',{},r.kind),el('dt',{},'命令或目标'),el('dd',{},el('code',{class:'wrap'},displayRecipe(r))),el('dt',{},'工作目录'),el('dd',{class:'wrap'},r.cwd||'不适用'))),failure=el('p',{class:'error-text',role:'alert'});message.append(failure);m=modal('确认配方',message,[button('取消',()=>{m.close();resolve();}),button('确认并执行',async e=>{const btn=e.currentTarget;btn.disabled=true;try{await api.request(`/projects/${p.id}/recipe-approval`,{method:'POST',body,signal});await api.request(`/projects/${p.id}/actions`,{method:'POST',body,signal});notify(r.kind==='command'?'已创建受管理运行':'已请求打开');m.close();resolve();}catch(ex){failure.textContent=ex.message;btn.disabled=false;}},'primary')],signal);m.dialog.addEventListener('close',()=>resolve(),{once:true});});}
 async function edit(p){try{await openRecipeEditor(p,context);await refresh();}catch(e){showError(e);}}
 function rename(p){
  if(!snapshot.capabilities?.project_names){notify('修改项目名称功能需要重启工作台。请先结束运行中的项目，再主动退出并双击启动。',true);return;}
  const revision=snapshot.revision;
  const failure=el('p',{class:'error-text',role:'alert',id:'project-name-error'});
  const name=el('input',{type:'text',value:p.name,maxLength:120,'aria-label':'项目名称','aria-describedby':'project-name-error',onBlur:()=>validate(),onInput:()=>{failure.textContent='';name.removeAttribute('aria-invalid');},onKeydown:e=>{if(e.key==='Enter'){e.preventDefault();save.click();}}});
  let m;
  function validate(){const valid=!!name.value.trim();failure.textContent=valid?'':'项目名称不能为空。';name.setAttribute('aria-invalid',String(!valid));return valid;}
  async function apply(reset){
   if(!reset&&!validate()){name.focus();return;}
   save.disabled=true;restore.disabled=true;failure.textContent='';
   try{await api.request(`/projects/${p.id}/name`,{method:reset?'DELETE':'PATCH',body:reset?undefined:{name:name.value},revision,signal});m.close();notify(reset?'已恢复默认名称':'项目名称已更新');await refresh();search.focus();}
   catch(e){if(e.name!=='AbortError'){failure.textContent=e.message;name.focus();}}
   finally{save.disabled=false;restore.disabled=!p.has_custom_name;}
  }
  const save=button('保存名称',()=>apply(false),'primary');
  const restore=button('恢复默认名称',()=>apply(true),'quiet',{disabled:!p.has_custom_name});
  m=modal('修改项目名称',el('div',{},el('p',{class:'muted'},'只修改工作台中的显示名称，不会重命名磁盘目录或改变启动命令。'),el('code',{class:'wrap'},p.path),field('项目名称',name,'1–120 个字符，保存时去掉首尾空白。'),el('p',{class:'muted small wrap'},'默认名称：'+(p.default_name||p.name)),failure),[restore,button('取消',()=>m.close()),save],signal);
  name.focus();name.select();
 }
 function remove(p){
  const revision=snapshot.revision;
  if(!revision){notify('新增移除与恢复功能需要重启工作台。请先结束运行中的项目，再主动退出并双击启动。',true);return;}
  const failure=el('p',{class:'error-text',role:'alert'});let m;
  m=modal('从工作台移除',el('div',{},el('p',{},'将“'+p.name+'”从工作台移除？'),el('code',{class:'wrap'},p.path),el('p',{class:'muted'},'仅从工作台移除，不删除本地文件。配方和使用记录会保留，可在设置的“已移除项目”中恢复。'),failure),[button('取消',()=>m.close()),button('确认移除',async e=>{
   const btn=e.currentTarget;btn.disabled=true;
   try{await api.request(`/projects/${p.id}`,{method:'DELETE',revision,signal});m.close();expanded=null;notify('已从工作台移除，可在设置中恢复');await refresh();search.focus();}
   catch(ex){failure.textContent=ex.message;btn.disabled=false;}
  },'danger')],signal);
 }

 function addManual(){let m;const path=el('input',{type:'text',required:true,placeholder:'目录绝对路径'}),name=el('input',{type:'text'}),failure=el('p',{role:'alert',class:'error-text'});m=modal('添加项目',el('div',{},el('p',{class:'muted'},'手动接入章节练习或未自动识别的目录。'),field('项目目录',path),field('显示名称（可选）',name),failure),[button('取消',()=>m.close()),button('添加',async e=>{const btn=e.currentTarget;btn.disabled=true;try{await api.request('/projects/manual',{method:'POST',body:{path:path.value,name:name.value||null},signal});m.close();await refresh();notify('项目已添加');}catch(ex){failure.textContent=ex.message;btn.disabled=false;}},'primary')],signal);}
 const connection=()=>render();window.addEventListener('workbench-connection',connection);const stopPoll=poll(refresh,signal);signal.addEventListener('abort',()=>window.removeEventListener('workbench-connection',connection),{once:true});return ()=>{stopPoll();window.removeEventListener('workbench-connection',connection);};
}
