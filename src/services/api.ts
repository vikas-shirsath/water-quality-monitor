import type { Alert, AnalyticsResponse, DashboardSummary, Device, Reading, Threshold } from '../types';
const base = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');
async function request<T>(path:string, init?:RequestInit):Promise<T>{const token=localStorage.getItem('wqm_access_token');const r=await fetch(`${base}${path}`,{...init,headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{ }),...init?.headers}});if(!r.ok)throw new Error(`API ${r.status}: ${await r.text()}`);return r.json();}
export const api={
 login:(username:string,password:string)=>request<{access_token:string;token_type:string;expires_in:number;username:string}>('/api/auth/login',{method:'POST',body:JSON.stringify({username,password})}),
 me:()=>request<{username:string}>('/api/auth/me'),
 dashboard:()=>request<DashboardSummary>('/api/dashboard'),
 readings:(q='')=>request<{items:Reading[];total:number}>(`/api/readings${q}`),
 alerts:()=>request<Alert[]>('/api/alerts'), devices:()=>request<Device[]>('/api/devices'),
 thresholds:()=>request<Threshold>('/api/thresholds'),
 saveThresholds:(x:Threshold)=>request<Threshold>('/api/thresholds',{method:'PUT',body:JSON.stringify(x)}),
 acknowledge:(id:number)=>request<Alert>(`/api/alerts/${id}/acknowledge`,{method:'POST'}),
 resolve:(id:number)=>request<Alert>(`/api/alerts/${id}/resolve`,{method:'POST'}),
 analytics:(parameter:string,range:string)=>request<AnalyticsResponse>(`/api/analytics?parameter=${parameter}&range=${range}`),
 exportCsv:async()=>{const token=localStorage.getItem('wqm_access_token');const r=await fetch(`${base}/api/readings/export.csv`,{headers:token?{Authorization:`Bearer ${token}`}:{}});if(!r.ok)throw new Error(`API ${r.status}: ${await r.text()}`);return r.blob();}
};
