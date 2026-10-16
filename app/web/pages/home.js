import {el,button,heading,icon,poll} from '../core/dom.js';
export function mount(container,context) {
 container.replaceChildren(heading('工作台','常用工具，从这里开始'));
 const columns=el('div',{class:'home-columns'}),available=el('section',{}),recent=el('section',{class:'recent'},el('h2',{},'最近使用'));columns.append(available,recent);
 const planned=el('section',{class:'planned-section'},el('h2',{},'规划中的功能'));container.append(columns,planned);
 const draw=modules=>{
  available.replaceChildren();recent.replaceChildren(el('h2',{},'最近使用'));planned.replaceChildren(el('h2',{},'规划中的功能'));
  let recentCount=0;
  for(const m of modules){if(m.status==='available'){
   const summary=m.summary||{};
   available.append(el('article',{class:'module-panel'},el('div',{class:'module-heading'},el('span',{class:'module-icon'},icon(m.icon)),el('div',{},el('h2',{},m.title),el('span',{class:'tag ready'},'可用'))),el('p',{class:'module-description'},m.description),el('div',{class:'module-summary'},(summary.metrics||[]).map(x=>el('span',{},el('b',{},x.value),' '+x.label))),el('div',{class:'module-bottom'},el('span',{class:'muted small'},summary.availability||'等待摘要'),summary.availability==='尚未配置扫描目录'?el('div',{class:'actions'},button('进入'+m.title,()=>context.navigate(m.route),'quiet'),button('设置扫描目录',()=>context.navigate('/settings'),'primary')):button('进入'+m.title,()=>context.navigate(m.route),'primary'))));
   for(const r of summary.recent_links||[]){recentCount++;recent.append(button(r.label,()=>context.navigate(r.route,r.params),'recent-row'));}
  }else planned.append(el('div',{class:'planned-row'},icon(m.icon),el('div',{},el('h3',{},m.title),el('p',{class:'muted'},m.description)),el('span',{class:'tag'},'规划中')));}
  if(!recentCount)recent.append(el('p',{class:'empty-inline muted'},'使用项目后，最近记录会出现在这里。'));
 };
 draw(context.modules);return poll(async()=>draw((await context.api.bootstrap(context.signal)).modules),context.signal);
}
