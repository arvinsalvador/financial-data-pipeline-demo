import { governedFetch } from "./context";
import { API_BASE_URL } from "./health";

interface Page<T> { items: T[]; total: number }
export interface PayrollAccount { id:number; account_name:string; source_account_code:string }
export interface PayrollRun { id:number; status:string; date_from:string; date_to:string; settlement_model:string; included_payroll_run_count:number; automatically_matched_count:number; suggested_match_count:number; partially_matched_count:number; exception_count:number; gross_pay_total:string; net_pay_total:string; bank_withdrawal_total:string; gl_payroll_expense_total:string; reconciliation_rate:string }
export interface PayrollGroup { id:number; payroll_run_id:number; status:string; payroll_total:string; bank_total:string; gl_total:string; confidence:string }
export interface PayrollControl { id:number; control_name:string; payroll_value:string|null; bank_value:string|null; gl_value:string|null; difference_value:string|null; status:string }
export interface PayrollReport { id:number; report_type:string; relative_path:string; file_size_bytes:number }
async function request<T>(path:string,init?:RequestInit):Promise<T>{const response=await governedFetch(`${API_BASE_URL}${path}`,init);const body=(await response.json()) as T&{detail?:string};if(!response.ok)throw new Error(body.detail??`Request failed (${response.status})`);return body;}
export const fetchPayrollAccounts=()=>request<PayrollAccount[]>("/reconciliations/payroll/accounts");
export async function fetchPayrollRuns(){return (await request<Page<PayrollRun>>("/reconciliations/payroll?page_size=100")).items;}
export const runPayroll=(account:number,from:string,to:string,model:string,force:boolean)=>request<PayrollRun>("/reconciliations/payroll",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({payroll_bank_account_id:account,date_from:from,date_to:to,settlement_model:model,force_rerun:force})});
export async function fetchPayrollGroups(id:number){return (await request<Page<PayrollGroup>>(`/reconciliations/payroll/${id}/groups?page_size=500`)).items;}
export const fetchPayrollControls=(id:number)=>request<PayrollControl[]>(`/reconciliations/payroll/${id}/control-totals`);
export const fetchPayrollReports=(id:number)=>request<PayrollReport[]>(`/reconciliations/payroll/${id}/reports`);
export const decidePayroll=(id:number,action:string)=>request(`/payroll-reconciliation-groups/${id}/${action}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({reason:`Operator ${action} from payroll reconciliation workbench`})});
