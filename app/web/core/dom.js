/** Text-only DOM building: project paths and names never become HTML. */
export function el(tag, props={}, ...children) {
  const node=document.createElement(tag);
  for(const [key,value] of Object.entries(props)) {
    if(key==='class') node.className=value;
    else if(key==='text') node.textContent=value;
    else if(key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(),value);
    else if(key in node && !key.startsWith('aria-')) node[key]=value;
    else node.setAttribute(key,String(value));
  }
  for(const child of children.flat(Infinity)) if(child!=null) node.append(child instanceof Node?child:document.createTextNode(String(child)));
  return node;
}
export const button=(text,handler,kind='',props={})=>el('button',{type:'button',class:'button '+kind,onClick:handler,...props},text);
export function heading(title,description,actions=[]) {return el('div',{class:'page-head'},el('div',{},el('h1',{},title),el('p',{class:'muted'},description)),el('div',{class:'actions'},actions));}
export function field(label,node,help='') {return el('label',{class:'field'},el('span',{},label),node,help?el('small',{class:'muted'},help):null);}
export function icon(name) {
  const paths={home:'M3 10 12 3l9 7v11h-6v-7H9v7H3z',projects:'M3 4h7v7H3z M14 4h7v7h-7z M3 15h7v6H3z M14 15h7v6h-7z',link:'M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2 M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2',calendar:'M4 5h16v16H4z M4 10h16 M8 3v4 M16 3v4',folder:'M3 5h6l2 3h10v12H3z',code:'m8 7-5 5 5 5 m8-10 5 5-5 5 M14 4l-4 16',arrow:'M5 12h14 m-6-6 6 6-6 6'};
  const n=document.createElementNS('http://www.w3.org/2000/svg','svg');n.setAttribute('viewBox','0 0 24 24');n.setAttribute('class','icon');n.setAttribute('aria-hidden','true');const p=document.createElementNS(n.namespaceURI,'path');p.setAttribute('d',paths[name]||paths.code);n.append(p);return n;
}
export const managedRecipe=r=>['command','script'].includes(r.kind);
export function recipeType(r) {
 if(r.kind==='script')return /\.ps1$/i.test(r.target)?'Windows PowerShell 脚本':/\.py$/i.test(r.target)?'Python 脚本':'Windows CMD 脚本';
 if(r.shell_command)return r.shell==='powershell'?'Windows PowerShell 命令':'Windows CMD 命令';
 return {command:'原生程序',app:'打开应用',directory:'打开文件夹',url:'打开网页'}[r.kind];
}
export function displayRecipe(r) {
 const quote=v=>'"'+v.replace(/(\\*)"/g,'$1$1\\"').replace(/(\\+)$/,'$1$1')+'"';
 if(r.shell_command)return r.shell_command;
 if(r.kind==='script'&&/\.ps1$/i.test(r.target))return '& '+[r.target,...(r.args||[])].map((v,i)=>i&&/^-[a-z_][a-z0-9_-]*(?::\$(?:true|false))?$/i.test(v)?v:"'"+v.replaceAll("'","''")+"'").join(' ');
 if(r.kind==='script'&&/\.(bat|cmd)$/i.test(r.target))return [r.target,...(r.args||[])].map(v=>'"'+v+'"').join(' ');
 const parts=r.kind==='script'?(/\.py$/i.test(r.target)?[r.program||'项目 Python',r.target,...(r.args||[])]:[r.target,...(r.args||[])]):[r.program,...(r.args||[])];
 return parts.filter(v=>v!==undefined&&v!==null).map(v=>!v||/[\s"]/.test(v)?quote(v):v).join(' ')||r.target;
}
export function displayExecution(execution){return [execution?.command_line,...Object.entries(execution?.environment||{}).map(([key,value])=>key+' = '+JSON.stringify(value))].filter(Boolean).join('\n');}
export async function copy(text,notify) {try{await navigator.clipboard.writeText(text);notify('已复制');}catch{notify('复制失败，请选中文本复制。',true);}}
export function modal(title,content,actions,signal) {
 const previous=document.activeElement;
 const d=el('dialog',{'aria-label':title,class:'modal'},el('h2',{},title),content,el('div',{class:'dialog-actions'},actions));
 document.body.append(d); d.showModal();
 const close=()=>{d.close();d.remove();if(previous?.isConnected)previous.focus();};
 signal?.addEventListener('abort',close,{once:true});d.addEventListener('close',()=>{signal?.removeEventListener('abort',close);d.remove();if(previous?.isConnected)previous.focus();},{once:true});
 return {dialog:d,close};
}
export function poll(fn,signal) {
 let timer,delay=2000;
 async function tick(){if(signal.aborted)return;try{await fn();delay=2000;}catch(e){if(e.name!=='AbortError')delay=Math.min(delay*2,30000);}if(!signal.aborted)timer=setTimeout(tick,document.hidden?Math.max(delay,10000):delay);}
 tick(); const onVisible=()=>{if(!document.hidden){clearTimeout(timer);tick();}};document.addEventListener('visibilitychange',onVisible);
 const stop=()=>{clearTimeout(timer);document.removeEventListener('visibilitychange',onVisible);};signal.addEventListener('abort',stop,{once:true});return stop;
}
