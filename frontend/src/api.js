let csrf='';
export const setCsrf=v=>{csrf=v||''};
export async function api(path, options={}) {
  const isForm=options.body instanceof FormData;
  const res=await fetch(`/api${path}`,{credentials:'include',...options,headers:{...(!isForm&&options.body?{'Content-Type':'application/json'}:{}),...(!['GET','HEAD'].includes(options.method||'GET')?{'X-CSRF-Token':csrf}:{}),...(options.headers||{})}});
  let out;try{out=await res.json()}catch{out={detail:'Respons server tidak valid'}}
  if(!res.ok){let detail=out?.detail||`HTTP ${res.status}`;if(typeof detail==='object')detail=detail.message||JSON.stringify(detail);throw new Error(detail)}
  return out;
}
export async function initializeSession(){const {user}=await api('/auth/me');const x=await api('/auth/csrf');setCsrf(x.csrf_token);return user}
export function post(path,payload){return api(path,{method:'POST',body:JSON.stringify(payload)})}
export function patch(path,payload){return api(path,{method:'PATCH',body:JSON.stringify(payload)})}
export function downloadCsv(filename,rows){if(!rows.length)return;const cols=Object.keys(rows[0]);const lines=[cols.join(','),...rows.map(row=>cols.map(k=>'"'+String(row[k]??'').replaceAll('"','""')+'"').join(','))];const blob=new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8;'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
