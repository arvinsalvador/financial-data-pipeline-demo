export type PageKey =
  | "sources"
  | "staging"
  | "canonical"
  | "generated"
  | "messy"
  | "validation"
  | "reconciliation"
  | "payroll"
  | "collections"
  | "governance";

export interface NavigationItem {
  label: string;
  page: PageKey;
  icon: string;
  group: "Data Foundation" | "Data Simulation" | "Data Quality" | "Reconciliation" | "Governance";
  viewerVisible: boolean;
}

export const NAVIGATION: NavigationItem[] = [
  { label: "Sources", page: "sources", icon: "SI", group: "Data Foundation", viewerVisible: true },
  { label: "Staging & mappings", page: "staging", icon: "SM", group: "Data Foundation", viewerVisible: false },
  { label: "Canonical data", page: "canonical", icon: "CD", group: "Data Foundation", viewerVisible: true },
  { label: "Generated data", page: "generated", icon: "GD", group: "Data Simulation", viewerVisible: true },
  { label: "Messy data", page: "messy", icon: "MD", group: "Data Simulation", viewerVisible: true },
  { label: "Validation", page: "validation", icon: "V", group: "Data Quality", viewerVisible: true },
  { label: "Bank reconciliation", page: "reconciliation", icon: "BR", group: "Reconciliation", viewerVisible: true },
  { label: "Payroll reconciliation", page: "payroll", icon: "PR", group: "Reconciliation", viewerVisible: true },
  { label: "Invoice & collections", page: "collections", icon: "IC", group: "Reconciliation", viewerVisible: true },
  { label: "Governance & audit", page: "governance", icon: "GA", group: "Governance", viewerVisible: false },
];

export const PAGE_COPY: Record<PageKey, { title: string; description: string }> = {
  sources: { title: "Source intake", description: "Register and inspect immutable financial source files." },
  staging: { title: "Staging & mappings", description: "Review parsed staging records and governed mappings." },
  canonical: { title: "Canonical data", description: "Explore normalized financial entities and lineage." },
  generated: { title: "Generated data", description: "Create deterministic business-source datasets." },
  messy: { title: "Messy data", description: "Generate controlled defects with known expectations." },
  validation: { title: "Validation", description: "Run transparent data-quality controls." },
  reconciliation: { title: "Bank reconciliation", description: "Reconcile bank activity to the general ledger." },
  payroll: { title: "Payroll reconciliation", description: "Reconcile payroll batches to bank and ledger evidence." },
  collections: { title: "Invoice & collections", description: "Reconcile invoices, payments, deposits, ledger entries, and AR aging." },
  governance: { title: "Governance & audit", description: "Review tenants, memberships, roles, and audit history." },
};
