export type Parameter = 'ph' | 'tds' | 'turbidity' | 'temperature';
export type Reading = { id: number; device_id: string; ph: number; tds: number; turbidity: number; temperature: number; created_at: string };
export type Alert = { id: number; device_id: string; parameter: Parameter; value: number; threshold: number; severity: 'INFO'|'WARNING'|'CRITICAL'; message: string; created_at: string; acknowledged: boolean; resolved_at?: string|null };
export type Device = { device_id: string; name: string; status: 'ONLINE'|'OFFLINE'; ip_address?: string|null; last_seen: string; firmware_version: string; sampling_interval: number; created_at: string };
export type Threshold = { ph_min:number;ph_max:number;tds_max:number;turbidity_max:number;temperature_min:number;temperature_max:number };
export type ModelAssessment = { score:number; prediction:'Good'|'Moderate'|'Poor'; basis:string; is_certified:false };
export type DashboardSummary = { reading:Reading; device:Device; alerts:Alert[]; thresholds:Threshold; system_status:string; model_assessment:ModelAssessment|null };
export type AnalyticsResponse = { average:number;minimum:number;maximum:number;violations:number;readings:Reading[] };
export type WebSocketMessage = { type:string; reading?:Reading; alert?:Alert; device?:Device };
export const PARAMS: {key:Parameter;label:string;unit:string;color:string;icon:string}[] = [
 {key:'ph',label:'pH level',unit:'pH',color:'#54d6b1',icon:'◉'}, {key:'tds',label:'Total dissolved solids',unit:'ppm',color:'#78a9ff',icon:'◈'},
 {key:'turbidity',label:'Turbidity',unit:'NTU',color:'#f2b968',icon:'◌'}, {key:'temperature',label:'Temperature',unit:'°C',color:'#b69aff',icon:'⌁'}
];
