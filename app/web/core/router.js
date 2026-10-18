export function navigate(route,params={}) {
 const target='#'+route+(Object.keys(params).length?'?'+new URLSearchParams(params):'');
 // Explicit navigation should reopen a result even when its URL is unchanged.
 if(location.hash===target)window.dispatchEvent(new HashChangeEvent('hashchange'));
 else location.hash=target;
}
export function createRouter(render){let controller,cleanup;
 async function route(){controller?.abort();cleanup?.();controller=new AbortController();const current=controller;const [path,query]=(location.hash.slice(1)||'/').split('?');try{const result=await render(path,new URLSearchParams(query),current.signal);if(current.signal.aborted)result?.();else cleanup=result;}catch(e){if(e.name!=='AbortError')console.error(e);}}
 window.addEventListener('hashchange',route);route();return ()=>{window.removeEventListener('hashchange',route);controller?.abort();cleanup?.();};
}
