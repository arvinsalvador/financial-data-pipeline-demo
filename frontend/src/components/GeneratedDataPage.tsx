import { useEffect, useState } from "react";
import {
  fetchGeneratedDatasets,
  fetchGeneratedFiles,
  fetchGeneratedLinks,
  fetchGeneratedRecords,
  fetchGenerationControls,
  fetchGenerationEligibility,
  generateDataset,
  type GeneratedDataset,
  type GeneratedFile,
  type GeneratedLink,
  type GenerationControl,
  type GenerationEligibility,
} from "../api/generation";
import { getDemoUser } from "../api/context";

export function GeneratedDataPage() {
  const [eligibility, setEligibility] = useState<GenerationEligibility[]>([]);
  const [normalizationRunId, setNormalizationRunId] = useState<number | null>(null);
  const [runs, setRuns] = useState<GeneratedDataset[]>([]);
  const [selected, setSelected] = useState<GeneratedDataset | null>(null);
  const [files, setFiles] = useState<GeneratedFile[]>([]);
  const [controls, setControls] = useState<GenerationControl[]>([]);
  const [links, setLinks] = useState<GeneratedLink[]>([]);
  const [ledger, setLedger] = useState<Record<string, string>[]>([]);
  const [seed, setSeed] = useState(20260714);
  const [generationDate, setGenerationDate] = useState("2026-07-14");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const canGenerate = getDemoUser() !== "viewer@demo.local";
  const selectedInput = eligibility.find((item) => item.normalization_run_id === normalizationRunId) ?? null;

  async function load() {
    const [inputs, history] = await Promise.all([
      fetchGenerationEligibility(),
      fetchGeneratedDatasets(),
    ]);
    setEligibility(inputs);
    setRuns(history);
    setNormalizationRunId((current) => {
      if (current && inputs.some((item) => item.normalization_run_id === current)) return current;
      return inputs.find((item) => item.eligible)?.normalization_run_id ?? inputs[0]?.normalization_run_id ?? null;
    });
  }

  useEffect(() => {
    let active = true;
    void Promise.all([fetchGenerationEligibility(), fetchGeneratedDatasets()])
      .then(([inputs, history]) => {
        if (!active) return;
        setEligibility(inputs);
        setRuns(history);
        setNormalizationRunId(inputs.find((item) => item.eligible)?.normalization_run_id ?? inputs[0]?.normalization_run_id ?? null);
      })
      .catch((error: unknown) => {
        if (active) setMessage(error instanceof Error ? error.message : "Unable to load generated data");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  async function inspect(run: GeneratedDataset) {
    setSelected(run);
    const [nextFiles, nextControls, nextLinks] = await Promise.all([
      fetchGeneratedFiles(run.id),
      fetchGenerationControls(run.id),
      fetchGeneratedLinks(run.id),
    ]);
    setFiles(nextFiles);
    setControls(nextControls);
    setLinks(nextLinks);
    const gl = nextFiles.find((file) => file.file_type === "general_ledger");
    setLedger(gl ? await fetchGeneratedRecords(gl.id) : []);
  }

  async function generate() {
    if (!selectedInput?.eligible) return;
    setBusy(true);
    setMessage(null);
    try {
      const run = await generateDataset(selectedInput.normalization_run_id, seed, generationDate);
      setMessage(run.no_op ? "Identical inputs already exist; returned the existing deterministic run." : `Generated ${run.file_count} files and ${run.record_count} records.`);
      await load();
      await inspect(run);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Generation failed");
    } finally {
      setBusy(false);
    }
  }

  return <section className="generated-page">
    <p className="eyebrow">Phase 6 · Clean deterministic business sources</p>
    <div className="section-heading"><div><h2>Generated data</h2><p>Choose an eligible canonical normalization snapshot, then create tenant-scoped CRM, receivables, payables, ledger, and assumption sources.</p></div></div>
    {loading && <p className="notice">Checking normalization eligibility…</p>}
    {!loading && eligibility.length === 0 && <p className="notice">No normalization runs exist for this tenant. Complete ingestion and normalization first.</p>}
    {eligibility.length > 0 && <div className="generation-form">
      <label>Normalization input
        <select value={normalizationRunId ?? ""} onChange={(event) => setNormalizationRunId(Number(event.target.value))}>
          {eligibility.map((item) => <option key={item.normalization_run_id} value={item.normalization_run_id}>Run #{item.normalization_run_id} · {item.status} · {item.eligible ? "eligible" : "not eligible"}</option>)}
        </select>
      </label>
      <label>Random seed<input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label>
      <label>Generation date<input type="date" value={generationDate} onChange={(event) => setGenerationDate(event.target.value)} /></label>
      {canGenerate && <button type="button" disabled={busy || !selectedInput?.eligible} onClick={() => void generate()}>{busy ? "Generating…" : "Generate dataset"}</button>}
    </div>}
    {selectedInput && <article>
      <div className="metric-grid">
        <div className="metric"><span>Source files</span><strong>{selectedInput.source_file_count}</strong></div>
        <div className="metric"><span>Bank transactions</span><strong>{selectedInput.canonical_counts.bank_transactions}</strong></div>
        <div className="metric"><span>Card transactions</span><strong>{selectedInput.canonical_counts.credit_card_transactions}</strong></div>
        <div className="metric"><span>Payroll entries</span><strong>{selectedInput.canonical_counts.payroll_entries}</strong></div>
        <div className="metric"><span>Lineage rows</span><strong>{selectedInput.canonical_counts.lineage}</strong></div>
      </div>
      {selectedInput.eligible ? <p className="notice">Ready for Generated Data.</p> : <p className="notice">This normalization snapshot is not eligible.</p>}
      {[...selectedInput.missing_prerequisites, ...selectedInput.blocking_conditions].map((reason) => <p className="upload-message" key={reason}>{reason}</p>)}
      {selectedInput.warnings.map((warning) => <p className="upload-message duplicate" key={warning}>{warning}</p>)}
      {selectedInput.already_generated_run_id && <p className="notice">Existing generated run #{selectedInput.already_generated_run_id}; identical inputs return that run.</p>}
    </article>}
    {!canGenerate && <p className="notice">This demo user can view generated data but cannot execute generation.</p>}
    {message && <p className="notice">{message}</p>}
    <h3>Generation history</h3>
    <div className="table-wrap"><table><thead><tr><th>Run</th><th>Normalization</th><th>Date</th><th>Seed</th><th>Status</th><th>Files</th><th>Records</th><th /></tr></thead><tbody>{runs.map((run) => <tr key={run.id}><td>{run.id}</td><td>{run.normalization_run_id ?? "Legacy"}</td><td>{run.generation_date}</td><td>{run.random_seed}</td><td>{run.status}</td><td>{run.file_count}</td><td>{run.record_count}</td><td><button className="text-button" onClick={() => void inspect(run)}>Inspect</button></td></tr>)}</tbody></table>{!runs.length && <p className="empty-row">No generated datasets yet. Select an eligible normalization run above.</p>}</div>
    {selected && <div className="generated-details">
      <div className="metric-grid"><div className="metric"><span>Customers</span><strong>{selected.generated_customer_count}</strong></div><div className="metric"><span>Vendors</span><strong>{selected.generated_vendor_count}</strong></div><div className="metric"><span>Invoices</span><strong>{selected.generated_invoice_count}</strong></div><div className="metric"><span>Journal entries</span><strong>{selected.generated_gl_entry_count}</strong></div></div>
      <h3>Generated files</h3><div className="table-wrap"><table><thead><tr><th>File</th><th>Rows</th><th>Checksum</th><th>Registered path</th></tr></thead><tbody>{files.map((file) => <tr key={file.id}><td>{file.filename}</td><td>{file.record_count}</td><td><code>{file.sha256_checksum.slice(0, 16)}…</code></td><td><code>{file.relative_path}</code></td></tr>)}</tbody></table></div>
      <h3>General ledger preview</h3><div className="table-wrap profile-table"><table><thead><tr><th>Journal</th><th>Date</th><th>Account</th><th>Debit</th><th>Credit</th><th>Source</th><th>Balance</th></tr></thead><tbody>{ledger.map((line) => <tr key={line.journal_line_id}><td>{line.journal_entry_id}</td><td>{line.entry_date}</td><td>{line.account_code} · {line.account_name}</td><td>{line.debit}</td><td>{line.credit}</td><td>{line.source_type} · {line.source_record_id}</td><td>Balanced</td></tr>)}</tbody></table></div>
      <h3>Authoritative controls</h3><div className="table-wrap"><table><thead><tr><th>Control</th><th>Expected</th><th>Actual</th><th>Status</th></tr></thead><tbody>{controls.map((control) => <tr key={control.id}><td>{control.control_name}</td><td>{control.expected_value}</td><td>{control.actual_value}</td><td>{control.status}</td></tr>)}</tbody></table></div>
      <h3>Canonical relationship explorer</h3><div className="table-wrap"><table><thead><tr><th>Generated record</th><th>Relationship</th><th>Canonical record</th></tr></thead><tbody>{links.map((link) => <tr key={link.id}><td>{link.generated_file_type} · {link.generated_record_key}</td><td>{link.relationship_type}</td><td>{link.related_entity_type} #{link.related_entity_id}</td></tr>)}</tbody></table>{!links.length && <p className="empty-row">No source relationships for this run.</p>}</div>
    </div>}
  </section>;
}
