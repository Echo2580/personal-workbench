import {el,button,field,modal,displayRecipe} from '../../core/dom.js';
export async function openRecipeEditor(project,context){
 const {api,signal,notify}=context,doc=await api.request(`/projects/${project.id}/recipes`,{signal});
 let draft={recipes:doc.recipes.map(({fingerprint,...r})=>r),primary_recipe_id:doc.primary_recipe_id};const original=JSON.stringify(draft);
 return new Promise(resolve=>{
 const error=el('p',{class:'error-text',role:'alert'}),body=el('div',{class:'drawer-body'}),active=project.active_run;let m;
 function dirty(){return original!==JSON.stringify(draft);}
 function close(){if(!dirty()||confirm('放弃尚未保存的修改？选择取消可继续编辑。')){m.close();resolve(false);}}
 const save=button('保存配方',async e=>{error.textContent='';const btn=e.currentTarget;if(!draft.primary_recipe_id){error.textContent='请选择新的主配方。';return;}if(draft.recipes.some(r=>!r.label.trim())){error.textContent='配方名称不能为空。';return;}btn.disabled=true;try{await api.request(`/projects/${project.id}/recipes`,{method:'PUT',body:draft,revision:doc.revision,signal});notify('配方已保存');m.close();resolve(true);}catch(ex){error.textContent=ex.message;btn.disabled=false;}},'primary');
 const restore=button('恢复自动识别',async e=>{if(!confirm('清除此项目的人工配方并恢复自动识别？'))return;const btn=e.currentTarget;btn.disabled=true;try{await api.request(`/projects/${project.id}/override`,{method:'DELETE',revision:doc.revision,signal});notify('已恢复自动识别');m.close();resolve(true);}catch(ex){error.textContent=ex.message;btn.disabled=!!active;}},'quiet',{disabled:!!active});
 function render(){body.replaceChildren(el('p',{class:'muted small'},'保存后采用人工覆盖，自动扫描不会撤销修改。命令语法为 Windows CMD；原生命令保留程序和参数数组。'));
 draft.recipes.forEach((r,i)=>{
  const locked=active?.recipe_id===r.id;
  const primary=el('input',{type:'radio',name:'primary-recipe',checked:draft.primary_recipe_id===r.id,disabled:!!active,onChange:()=>draft.primary_recipe_id=r.id});
  const label=el('input',{value:r.label,disabled:locked,onInput:e=>r.label=e.target.value});
  const kind=el('select',{value:r.kind,disabled:locked,onChange:e=>{const id=r.id,label=r.label;Object.keys(r).forEach(k=>delete r[k]);Object.assign(r,{id,label,kind:e.target.value,args:[],...(e.target.value==='command'?{cwd:project.path,shell_command:''}:e.target.value==='app'?{cwd:project.path,program:''}:{target:''})});render();}},[['command','执行命令'],['app','打开应用 / IDE'],['directory','打开文件夹'],['url','打开网页']].map(([value,label])=>el('option',{value,selected:value===r.kind},label)));
  const section=el('fieldset',{class:'recipe-form'},el('legend',{},'配方 '+(i+1)),el('div',{class:'recipe-form-top'},el('label',{class:'radio-label'},primary,'主配方'),button('删除',()=>{draft.recipes.splice(i,1);if(draft.primary_recipe_id===r.id)draft.primary_recipe_id=null;render();},'quiet small-button',{disabled:locked||draft.recipes.length===1})),field('配方名称',label),field('类型',kind));
  if(locked)section.append(el('p',{class:'warning small'},'运行中的配方已锁定，请先停止项目。'));
  if(r.kind==='command'){
   if(r.program){section.append(el('code',{class:'native-summary wrap'},displayRecipe(r)),button('改为一行 CMD 命令',()=>{const command=displayRecipe(r);delete r.program;r.args=[];r.shell_command=command;render();},'quiet small-button',{disabled:locked}));}
   else section.append(field('Windows CMD 命令',el('textarea',{rows:2,value:r.shell_command||'',disabled:locked,onInput:e=>r.shell_command=e.target.value}),'例如使用已有解释器运行脚本；不自动安装项目依赖。'));
  }
  if(r.kind==='app')section.append(field('应用可执行文件',el('input',{value:r.program||'',onInput:e=>r.program=e.target.value})),field('应用参数（每行一项）',el('textarea',{rows:2,value:(r.args||[]).join('\n'),onInput:e=>r.args=e.target.value.split('\n').filter(x=>x!=='')})));
  if(['command','app'].includes(r.kind))section.append(field('工作目录',el('input',{value:r.cwd||project.path,disabled:locked,onInput:e=>r.cwd=e.target.value})));
  else section.append(field(r.kind==='url'?'网页地址或本项目 index.html':'文件夹路径',el('input',{value:r.target||'',onInput:e=>r.target=e.target.value})));
  body.append(section);
 });
 body.append(button('添加配方',()=>{draft.recipes.push({id:crypto.randomUUID(),label:'新配方',kind:'command',cwd:project.path,shell_command:'',args:[]});render();},'add-recipe'));}
 render();m=modal('编辑配方',el('div',{class:'drawer-content'},el('p',{class:'mono muted wrap drawer-path'},project.path),body,error),[restore,button('取消',close),save],signal);m.dialog.classList.add('drawer');m.dialog.addEventListener('cancel',e=>{e.preventDefault();close();});m.dialog.addEventListener('close',()=>resolve(false),{once:true});
 });
}
