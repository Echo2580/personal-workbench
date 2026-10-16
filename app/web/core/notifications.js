import {el} from './dom.js';
export function notify(message,error=false) {const n=el('div',{class:'toast'+(error?' error':''),role:error?'alert':'status'},message);document.querySelector('#notifications').append(n);setTimeout(()=>n.remove(),5500);}
