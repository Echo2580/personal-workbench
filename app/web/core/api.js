let token='',connected=null;
const connection=value=>{if(connected===value)return;connected=value;window.dispatchEvent(new CustomEvent('workbench-connection',{detail:value}));};
export const api={
 get connected(){return connected;},
 async bootstrap(signal){const result=await this.request('/bootstrap',{signal,bootstrap:true});token=result.token;return result;},
 /* 裸 fetch：给需要自己解析响应（文本流、二进制原图、multipart 上传）的模块用。
    自动补 X-Workbench-Token；path 可以带 /api/v1 前缀也可以省略。 */
 raw(path,{method='GET',body,headers,signal}={}){
  const url=path.startsWith('/api/v1/')?path:'/api/v1'+path;
  return fetch(url,{method,signal,headers:{'X-Workbench-Token':token,...(headers||{})},...(body===undefined?{}:{body})});
 },
 async request(path,{method='GET',body,signal,revision,bootstrap=false,retried=false}={}) {
  let response;
  try{response=await fetch('/api/v1'+path,{method,signal,headers:{...(bootstrap?{}:{'X-Workbench-Token':token}),...(body===undefined?{}:{'Content-Type':'application/json'}),...(revision?{'If-Match':revision}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})});}
  catch(e){if(e.name!=='AbortError')connection(false);throw e;}
  connection(true);
  const noContent=response.status===204||response.headers.get('content-length')==='0';
  const data=noContent?null:await response.json();
  if(response.status===403&&data?.error?.code==='invalid_token'&&method==='GET'&&!bootstrap&&!retried){await this.bootstrap(signal);return this.request(path,{method,body,signal,revision,retried:true});}
  if(!response.ok){const e=new Error(data?.error?.message||'请求失败');Object.assign(e,data?.error,{status:response.status});throw e;}
  return data;
 }
};
