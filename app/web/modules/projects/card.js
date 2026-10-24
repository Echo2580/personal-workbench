import {el,button,displayRecipe,copy,icon} from '../../core/dom.js';
export const actionLabel=r=>({command:'启动项目',directory:'打开文件夹',url:'打开网页',app:'打开应用'})[r.kind];
const states={launching:'启动中',running:'运行中',stopping:'停止中',stopped:'已停止',exited:'已结束',failed:'异常退出',interrupted:'已中断'};
export function renderProjectCard(p,c){
 const active=p.active_run,run=active||p.last_run,primary=p.recipes.find(r=>r.id===p.primary_recipe_id),state=run?(run.exit_reason==='start_failed'?'启动失败':states[run.status]):'未运行';
 const status=el('span',{class:'tag '+(active?'ready':run?.status==='failed'?'bad':'')},state);
 const card=el('article',{class:'project-card',id:'project-'+p.id},el('div',{class:'card-heading'},el('span',{class:'project-icon'},icon(p.type==='web'?'link':'code')),el('div',{class:'card-title'},el('h2',{title:p.name},p.name),el('span',{class:'muted small'},({python:'Python',node:'Node',web:'网页',go:'Go',rust:'Rust',other:'其他'})[p.type]||p.type)),status));
 card.append(el('div',{class:'path-line'},el('code',{class:'path',title:p.path},p.path),button('复制',()=>copy(p.path,c.notify),'quiet small-button',{'aria-label':'复制路径 '+p.name})),el('div',{class:'card-meta'},el('span',{},p.recipe_source==='manual'?'人工配方':'自动识别'),el('span',{title:p.last_action_at?new Date(p.last_action_at).toLocaleString():''},p.last_action_at?'上次使用 '+new Date(p.last_action_at).toLocaleString():'尚未使用')));
 if(p.availability!=='available')card.append(el('p',{class:'error-text small'},p.availability==='missing'?'项目目录不存在，请恢复路径。':'扫描根目录不可访问，保留上次结果。'));
 if(p.type==='python'&&!p.recipes.some(r=>r.kind==='command'))card.append(el('p',{class:'warning small'},'需要选择 Python 入口，请编辑配方。'),el('p',{class:'muted small wrap'},(p.evidence||[]).join('；')));
 if(!p.recipes.some(r=>r.kind==='command')&&['node','go','rust'].includes(p.type))card.append(el('p',{class:'warning small'},'尚未确定启动入口，请查看识别依据并编辑配方。'),el('p',{class:'muted small wrap'},(p.evidence||[]).join('；')));
 if(run?.status==='failed'){
  const details=el('div',{class:'launch-diagnostics small'},el('p',{class:'error-text wrap'},run.error||'启动的进程异常退出。'));
  if(run.exit_code!==null&&run.exit_code!==undefined)details.append(el('p',{class:'error-text'},`退出码：${run.exit_code}`+(run.exit_code<0?`（0x${(run.exit_code>>>0).toString(16).toUpperCase()}）`:'')));
  const executed=run.project_snapshot?.recipes?.find(r=>r.id===run.recipe_id);
  if(executed){details.append(el('p',{class:'muted wrap'},'当时的命令：',el('code',{class:'wrap'},displayRecipe(executed))));if(executed.cwd)details.append(el('p',{class:'muted wrap'},'工作目录：',el('code',{class:'wrap'},executed.cwd)));}
  details.append(el('p',{class:'muted wrap'},'未保存终端输出；请在项目终端查看具体报错。上述信息不代表业务已就绪。'));
  card.append(details);
 }
 const blocked=!c.online||c.busy===p.id;
 card.append(el('div',{class:'card-actions'},button(active&&primary.kind==='command'?'运行中':(primary.kind==='command'?'启动项目':primary.label),()=>c.execute(p,primary),'primary',{'data-online-action':'true',disabled:blocked||(primary.kind==='command'&&!!active)||p.availability==='missing'}),active?button('停止',()=>c.stop(p),'danger',{disabled:blocked||active.status==='stopping','data-online-action':'true'}):null,button('配方 '+p.recipes.length,()=>c.expand(p.id),'',{'aria-expanded':String(c.expanded===p.id)})));
 card.append(el('div',{class:'card-footer'},button('修改名称',()=>c.rename(p),'quiet small-button',{disabled:blocked,'data-online-action':'true'}),button('从工作台移除',()=>c.remove(p),'quiet small-button',{'aria-label':'从工作台移除',title:active?'请先停止项目，再从工作台移除。':'仅影响工作台展示，可在设置中恢复',disabled:blocked||!!active,'data-online-action':'true'})));
 if(active)card.append(el('p',{class:'muted small'},'进程存在；业务是否就绪请在项目终端或网页确认。'));
 if(c.expanded===p.id){const list=el('div',{class:'recipe-list'});for(const r of p.recipes)list.append(el('div',{class:'recipe-row'},el('div',{class:'recipe-detail'},el('div',{},el('strong',{},r.label),' ',r.id===p.primary_recipe_id?el('span',{class:'tag'},'主配方'):null,el('span',{class:'muted small'},' '+r.kind)),el('code',{class:'command wrap'},displayRecipe(r)),r.cwd?el('p',{class:'muted small wrap'},'工作目录：'+r.cwd):null),el('div',{class:'recipe-controls'},button('复制',()=>copy(displayRecipe(r),c.notify),'quiet small-button'),button(r.kind==='command'?'运行':'打开',()=>c.execute(p,r),'small-button',{disabled:blocked||(r.kind==='command'&&!!active),'data-online-action':'true'}))));list.append(button('编辑配方',()=>c.edit(p),'quiet'));card.append(list);}
 return card;
}
