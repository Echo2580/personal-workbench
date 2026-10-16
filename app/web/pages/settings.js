import {el,heading} from '../core/dom.js';
import {moduleLoaders} from '../core/module-loaders.js';
export async function mount(container,context){container.replaceChildren(heading('设置','管理本机目录和项目默认环境'));const cleanup=[];for(const m of context.modules){if(m.status==='available'&&m.settings_route&&moduleLoaders[m.id]){const module=await moduleLoaders[m.id]();if(context.signal.aborted)return;const section=el('section',{});container.append(section);const stop=await module.mountSettings?.(section,context);if(stop)cleanup.push(stop);}}return ()=>cleanup.forEach(fn=>fn());}
