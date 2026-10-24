import {el,button,field,modal} from '../../core/dom.js';
export async function openRecipeEditor(project,context,initialKind){
 const {api,signal,notify}=context,doc=await api.request(`/projects/${project.id}/recipes`,{signal});
 const draft={recipes:doc.recipes.map(({fingerprint,execution,...r})=>r),primary_recipe_id:doc.primary_recipe_id};
 const original=JSON.stringify(draft);let candidates=null,candidateError='',loading=false,m;
 const error=el('p',{class:'error-text',role:'alert'}),body=el('div',{class:'drawer-body'}),active=project.active_run;
 function newRecipe(kind){return {id:crypto.randomUUID(),label:kind==='script'?'运行脚本':'自定义命令',kind,cwd:project.path,args:[],...(kind==='script'?{target:''}:{shell:'cmd',shell_command:''})};}
 if(initialKind)draft.recipes.push(newRecipe(initialKind));
 return new Promise(resolve=>{
 function close(){if(original===JSON.stringify(draft)||confirm('放弃尚未保存的修改？选择取消可继续编辑。')){m.close();resolve(false);}}
 const save=button('保存配方',async e=>{
  error.textContent='';const btn=e.currentTarget;
  if(!draft.primary_recipe_id){error.textContent='请选择新的主配方。';return;}
  if(draft.recipes.some(r=>!r.label.trim())){error.textContent='配方名称不能为空。';return;}
  if(draft.recipes.some(r=>r.kind==='command'&&!r.program&&!r.shell_command?.trim())){error.textContent='请填写自定义命令。';return;}
  if(draft.recipes.some(r=>r.kind==='script'&&!r.target?.trim())){error.textContent='请选择或填写脚本路径。';return;}
  btn.disabled=true;
  try{await api.request(`/projects/${project.id}/recipes`,{method:'PUT',body:draft,revision:doc.revision,signal});notify('配方已保存');m.close();resolve(true);}
  catch(ex){error.textContent=ex.message;btn.disabled=false;}
 },'primary');
 const restore=button('恢复自动识别',async e=>{if(!confirm('清除此项目的人工配方并恢复自动识别？'))return;const btn=e.currentTarget;btn.disabled=true;try{await api.request(`/projects/${project.id}/override`,{method:'DELETE',revision:doc.revision,signal});notify('已恢复自动识别');m.close();resolve(true);}catch(ex){error.textContent=ex.message;btn.disabled=!!active;}},'quiet',{disabled:!!active});
 async function loadCandidates(){loading=true;render();try{candidates=await api.request(`/projects/${project.id}/scripts`,{signal});}catch(e){if(e.name!=='AbortError')candidateError=e.message;}finally{loading=false;if(m?.dialog.isConnected)render();}}
 function add(kind){draft.recipes.push(newRecipe(kind));render();body.lastElementChild?.scrollIntoView({block:'nearest'});}
 function render(){
  body.replaceChildren(el('p',{class:'muted small'},'自定义 CMD / Windows PowerShell 命令，或选择项目内脚本。保存不会执行；首次运行或内容更改后需要确认。'),el('div',{class:'recipe-add-actions'},button('新增自定义命令',()=>add('command'),'add-recipe'),button('新增运行脚本',()=>add('script'),'add-recipe')));
  draft.recipes.forEach((r,i)=>{
   const locked=active?.recipe_id===r.id;
   const primary=el('input',{type:'radio',name:'primary-recipe',checked:draft.primary_recipe_id===r.id,disabled:!!active,onChange:()=>draft.primary_recipe_id=r.id});
   const label=el('input',{value:r.label,disabled:locked,onInput:e=>r.label=e.target.value});
   const kind=el('select',{disabled:locked,onChange:e=>{const id=r.id,label=r.label,kind=e.target.value;Object.keys(r).forEach(k=>delete r[k]);Object.assign(r,{id,label,kind,args:[],...(['command','script'].includes(kind)?{...newRecipe(kind),id,label}:kind==='app'?{cwd:project.path,program:''}:{target:''})});render();}},[['command','执行命令'],['script','运行脚本'],['app','打开应用 / IDE'],['directory','打开文件夹'],['url','打开网页']].map(([value,label])=>el('option',{value,selected:value===r.kind},label)));
   const section=el('fieldset',{class:'recipe-form'},el('legend',{},'配方 '+(i+1)),el('div',{class:'recipe-form-top'},el('label',{class:'radio-label'},primary,'主配方'),button('删除',()=>{draft.recipes.splice(i,1);if(draft.primary_recipe_id===r.id)draft.primary_recipe_id=null;render();},'quiet small-button',{disabled:locked||draft.recipes.length===1})),field('配方名称',label),field('类型',kind));
   if(locked)section.append(el('p',{class:'warning small'},'运行中的配方已锁定，请先停止项目。'));
   if(r.kind==='command'){
    const native=r.program!==undefined&&r.program!==null,mode=native?'native':r.shell||'cmd';
    section.append(field('命令方式',el('select',{disabled:locked,onChange:e=>{const mode=e.target.value,command=r.shell_command||'';if(mode==='native'){delete r.shell_command;r.shell='cmd';r.program='';r.args=[];}else{delete r.program;r.args=[];r.shell=mode;r.shell_command=command;}render();}},[['cmd','Windows CMD'],['powershell','Windows PowerShell'],['native','原生程序 + 参数']].map(([value,label])=>el('option',{value,selected:value===mode},label)))));
    if(native)section.append(field('可执行程序',el('input',{value:r.program,disabled:locked,onInput:e=>r.program=e.target.value})),argsField(r,locked));
    else section.append(field(r.shell==='powershell'?'Windows PowerShell 命令':'Windows CMD 命令',el('textarea',{'aria-label':r.shell==='powershell'?'Windows PowerShell 命令':'Windows CMD 命令',rows:4,value:r.shell_command||'',disabled:locked,onInput:e=>r.shell_command=e.target.value}),r.shell==='powershell'?'支持变量、管道和多行。使用 Windows PowerShell，不更改或绕过系统执行策略。':'按 CMD 语法填写完整命令。'));
   }
   if(r.kind==='script'){
    section.append(field('脚本路径',el('input',{'aria-label':'脚本路径',value:r.target||'',placeholder:'例如 scripts\\启动.ps1',disabled:locked,onInput:e=>r.target=e.target.value}),'可填项目内相对路径或绝对路径，支持 .bat / .cmd / .ps1 / .py。'));
    if(candidates){section.append(field('项目内脚本候选',el('select',{disabled:locked,onChange:e=>{if(e.target.value){r.target=e.target.value;delete r.program;render();}}},el('option',{value:''},'选择脚本（不会运行）'),candidates.candidates.map(value=>el('option',{value},value)))));if(!candidates.candidates.length)section.append(el('p',{class:'muted small'},'未找到候选，可直接填写路径。'));section.append(el('p',{class:'muted small'},'仅查看项目根目录及 scripts / bin / tools 的直接文件，最多 400 项、100 个脚本；排除依赖、环境和链接。'+(candidates.limited?'已达到候选预算，可手填路径。':'')),...(candidates.warnings||[]).map(text=>el('p',{class:'warning small wrap'},text)));}
    else section.append(button(loading?'正在读取候选…':'查看项目内脚本',loadCandidates,'quiet small-button',{disabled:loading||locked}),candidateError?el('p',{class:'error-text small'},candidateError):null);
    section.append(argsField(r,locked),el('p',{class:'muted small'},'参数每行一项，空格和引号按原文填写，无需再包外层引号。批处理不支持字面双引号或换行参数，可改用自定义 CMD 命令。Python 沿用项目 .venv / venv 或设置中的解释器；.ps1 遵循系统执行策略。'));
   }
   if(r.kind==='app')section.append(field('应用可执行文件',el('input',{value:r.program||'',disabled:locked,onInput:e=>r.program=e.target.value})),argsField(r,locked));
   if(['command','script','app'].includes(r.kind))section.append(field('工作目录',el('input',{'aria-label':'工作目录',value:r.cwd||project.path,disabled:locked,onInput:e=>r.cwd=e.target.value}),'填写已有目录的绝对路径。脚本相对路径始终相对于项目根目录。'));
   else section.append(field(r.kind==='url'?'网页地址或本项目 index.html':'文件夹路径',el('input',{value:r.target||'',disabled:locked,onInput:e=>r.target=e.target.value})));
   body.append(section);
  });
 }
 function argsField(r,locked){return field('参数（每行一项）',el('textarea',{rows:3,value:(r.args||[]).join('\n'),disabled:locked,onInput:e=>r.args=e.target.value.split('\n').filter(x=>x!=='')}));}
 render();m=modal('编辑配方',el('div',{class:'drawer-content'},el('p',{class:'mono muted wrap drawer-path'},project.path),body,error),[restore,button('取消',close),save],signal);m.dialog.classList.add('drawer');m.dialog.addEventListener('cancel',e=>{e.preventDefault();close();});m.dialog.addEventListener('close',()=>resolve(false),{once:true});
 if(initialKind)body.lastElementChild?.scrollIntoView({block:'nearest'});
 });
}
