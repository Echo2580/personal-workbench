export function navigate(route,params={}) {location.hash='#'+route+(Object.keys(params).length?'?'+new URLSearchParams(params):'');}
export function createRouter(render){let controller,cleanup;
 async function route(){controller?.abort();cleanup?.();controller=new AbortController();const current=controller;const [path,query]=(location.hash.slice(1)||'/').split('?');try{const result=await render(path,new URLSearchParams(query),current.signal);if(current.signal.aborted)result?.();else cleanup=result;}catch(e){if(e.name!=='AbortError')console.error(e);}}
 window.addEventListener('hashchange',route);route();return ()=>{window.removeEventListener('hashchange',route);controller?.abort();cleanup?.();};
}
