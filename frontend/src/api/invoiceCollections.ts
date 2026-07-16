import { governedFetch } from "./context";
import { API_BASE_URL } from "./health";

interface Page<T> { items: T[]; total: number }
export interface CollectionsAccount { id:number; account_name:string; source_account_code:string }
export interface CollectionsRun { id:number; status:string; date_from:string; date_to:string; aging_as_of_date:string; included_customer_count:number; included_deal_count:number; included_invoice_count:number; included_payment_count:number; included_bank_deposit_count:number; included_gl_record_count:number; automatically_matched_count:number; partially_matched_count:number; unmatched_invoice_count:number; unmatched_payment_count:number; exception_count:number; invoice_total:string; invoice_paid_total:string; invoice_balance_total:string; payment_total:string; bank_deposit_total:string; matched_collection_total:string; reconciliation_rate:string }
export interface CollectionsGroup { id:number; group_type:string; status:string; confidence:string; invoice_total:string; payment_total:string; deposit_total:string; gl_total:string; matched_amount:string; remaining_amount:string; difference_amount:string; auto_accepted:boolean; metadata_json:{invoice?:{invoice_id?:string;invoice_number?:string;customer_id?:string;deal_id?:string;invoice_date?:string;due_date?:string;balance_due?:string}}|null }
export interface CollectionsControl { id:number; control_name:string; invoice_value:string|null; payment_value:string|null; deposit_value:string|null; gl_value:string|null; difference_value:string|null; tolerance:string; status:string }
export interface AgingSnapshot { id:number; as_of_date:string; customer_id:string; invoice_count:number; current_amount:string; days_1_30_amount:string; days_31_60_amount:string; days_61_90_amount:string; over_90_days_amount:string; total_outstanding:string }
export interface CollectionsReport { id:number;report_type:string;relative_path:string;file_size_bytes:number }
export interface CollectionPayment { payment_id:string;payment_reference:string;customer_id:string;payment_date:string;payment_amount:string;applied_amount:string;unapplied_amount:string;invoice_count:number;deposit_status:string;gl_status:string;overall_status:string }
export interface CollectionException { id:number;exception_code:string;severity:string;invoice_id:string|null;payment_id:string|null;bank_transaction_id:number|null;gl_record_id:string|null;message:string;status:string }
async function request<T>(path:string,init?:RequestInit):Promise<T>{const response=await governedFetch(`${API_BASE_URL}${path}`,init);const body=(await response.json()) as T&{detail?:string};if(!response.ok)throw new Error(body.detail??`Request failed (${response.status})`);return body;}
export const fetchCollectionsAccounts=()=>request<CollectionsAccount[]>("/reconciliations/invoice-collections/accounts");
export async function fetchCollectionsRuns(){return (await request<Page<CollectionsRun>>("/reconciliations/invoice-collections?page_size=100")).items;}
export const runCollections=(account:number,from:string,to:string,aging:string,force:boolean)=>request<CollectionsRun>("/reconciliations/invoice-collections",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({bank_account_id:account,date_from:from,date_to:to,aging_as_of_date:aging,force_rerun:force})});
export async function fetchCollectionGroups(id:number){return (await request<Page<CollectionsGroup>>(`/reconciliations/invoice-collections/${id}/groups?page_size=500`)).items;}
export const fetchCollectionControls=(id:number)=>request<CollectionsControl[]>(`/reconciliations/invoice-collections/${id}/control-totals`);
export const fetchCollectionAging=(id:number)=>request<AgingSnapshot[]>(`/reconciliations/invoice-collections/${id}/ar-aging`);
export const fetchCollectionReports=(id:number)=>request<CollectionsReport[]>(`/reconciliations/invoice-collections/${id}/reports`);
export async function fetchCollectionPayments(id:number){return (await request<Page<CollectionPayment>>(`/reconciliations/invoice-collections/${id}/payments?page_size=200`)).items;}
export async function fetchCollectionExceptions(id:number){return (await request<Page<CollectionException>>(`/reconciliations/invoice-collections/${id}/exceptions?page_size=200`)).items;}
export const decideCollection=(id:number,action:string)=>request<CollectionsGroup>(`/invoice-collections-groups/${id}/${action}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({reason:`Operator ${action} from invoice collections workbench`})});
