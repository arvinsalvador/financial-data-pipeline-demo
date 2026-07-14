import { useEffect, useState } from "react";
import { fetchGeneratedDatasets, fetchGeneratedFiles, fetchGeneratedLinks, fetchGeneratedRecords, fetchGenerationControls, generateDataset, type GeneratedDataset, type GeneratedFile, type GeneratedLink, type GenerationControl } from "../api/generation";
import { getDemoUser } from "../api/context";

export function GeneratedDataPage() {
  const [runs, setRuns] = useState<GeneratedDataset[]>([]);
  const [selected, setSelected] = useState<GeneratedDataset | null>(null);
  const [files, setFiles] = useState<GeneratedFile[]>([]);
  const [controls, setControls] = useState<GenerationControl[]>([]);
  const [links, setLinks] = useState<GeneratedLink[]>([]);
  const [ledger, setLedger] = useState<Record<string, string>[]>([]);
  const [seed, setSeed] = useState(20260714);
  const [generationDate, setGenerationDate] = useState("2026-07-14");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const canGenerate = getDemoUser() !== "viewer@demo.local";
  async function load() { setRuns(await fetchGeneratedDatasets()); }
  useEffect(() => {
    let active = true;
    void fetchGeneratedDatasets()
      .then((items) => {
        if (active) setRuns(items);
      })
      .catch((error: unknown) => {
        if (active) {
          setMessage(error instanceof Error ? error.message : "Unable to load generated data");
        }
      });
    return () => {
      active = false;
    };
  }, []);
  async function inspect(run: GeneratedDataset) { setSelected(run); const [nextFiles, nextControls, nextLinks] = await Promise.all([fetchGeneratedFiles(run.id), fetchGenerationControls(run.id), fetchGeneratedLinks(run.id)]); setFiles(nextFiles); setControls(nextControls); setLinks(nextLinks); const gl = nextFiles.find((file) => file.file_type === "general_ledger"); setLedger(gl ? await fetchGeneratedRecords(gl.id) : []); }
  async function generate() { setBusy(true); setMessage(null); try { const run = await generateDataset(seed, generationDate); setMessage(run.no_op ? "Identical inputs already exist; returned the byte-identical run." : `Generated ${run.file_count} files and ${run.record_count} records.`); await load(); await inspect(run); } catch (error) { setMessage(error instanceof Error ? error.message : "Generation failed"); } finally { setBusy(false); } }
  return <section className="generated-page"><p className="eyebrow">Phase 6 · Clean deterministic business sources</p><div className="section-heading"><div><h2>Generated data</h2><p>CRM, receivables, payables, ledger, and forecast assumptions linked to canonical history.</p></div></div>{canGenerate && <div className="generation-form"><label>Random seed<input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label><label>Generation date<input type="date" value={generationDate} onChange={(event) => setGenerationDate(event.target.value)} /></label><button type="button" disabled={busy} onClick={() => void generate()}>{busy ? "Generating…" : "Generate dataset"}</button></div>}{message && <p className="notice">{message}</p>}<h3>Generation history</h3><div className="table-wrap"><table><thead><tr><th>Run</th><th>Date</th><th>Seed</th><th>Status</th><th>Files</th><th>Records</th><th /></tr></thead><tbody>{runs.map((run) => <tr key={run.id}><td>{run.id}</td><td>{run.generation_date}</td><td>{run.random_seed}</td><td>{run.status}</td><td>{run.file_count}</td><td>{run.record_count}</td><td><button className="text-button" onClick={() => void inspect(run)}>Inspect</button></td></tr>)}</tbody></table>{!runs.length && <p className="empty-row">No generated datasets yet.</p>}</div>{selected && <div className="generated-details"><div className="metric-grid"><div className="metric"><span>Customers</span><strong>{selected.generated_customer_count}</strong></div><div className="metric"><span>Vendors</span><strong>{selected.generated_vendor_count}</strong></div><div className="metric"><span>Invoices</span><strong>{selected.generated_invoice_count}</strong></div><div className="metric"><span>Journal entries</span><strong>{selected.generated_gl_entry_count}</strong></div></div><h3>Generated files</h3><div className="table-wrap"><table><thead><tr><th>File</th><th>Rows</th><th>Checksum</th><th>Registered path</th></tr></thead><tbody>{files.map((file) => <tr key={file.id}><td>{file.filename}</td><td>{file.record_count}</td><td><code>{file.sha256_checksum.slice(0, 16)}…</code></td><td><code>{file.relative_path}</code></td></tr>)}</tbody></table></div><h3>General ledger preview</h3><div className="table-wrap profile-table"><table><thead><tr><th>Journal</th><th>Date</th><th>Account</th><th>Debit</th><th>Credit</th><th>Source</th><th>Balance</th></tr></thead><tbody>{ledger.map((line) => <tr key={line.journal_line_id}><td>{line.journal_entry_id}</td><td>{line.entry_date}</td><td>{line.account_code} · {line.account_name}</td><td>{line.debit}</td><td>{line.credit}</td><td>{line.source_type} · {line.source_record_id}</td><td>Balanced</td></tr>)}</tbody></table></div><h3>Authoritative controls</h3><div className="table-wrap"><table><thead><tr><th>Control</th><th>Expected</th><th>Actual</th><th>Status</th></tr></thead><tbody>{controls.map((control) => <tr key={control.id}><td>{control.control_name}</td><td>{control.expected_value}</td><td>{control.actual_value}</td><td>{control.status}</td></tr>)}</tbody></table></div><h3>Canonical relationship explorer</h3><div className="table-wrap"><table><thead><tr><th>Generated record</th><th>Relationship</th><th>Canonical record</th></tr></thead><tbody>{links.map((link) => <tr key={link.id}><td>{link.generated_file_type} · {link.generated_record_key}</td><td>{link.relationship_type}</td><td>{link.related_entity_type} #{link.related_entity_id}</td></tr>)}</tbody></table>{!links.length && <p className="empty-row">No source relationships for this run.</p>}</div></div>}</section>;
}
