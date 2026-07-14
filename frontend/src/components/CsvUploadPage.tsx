import { useEffect, useRef, useState } from "react";

import {
  fetchSourceFile,
  fetchSourceFiles,
  fetchLatestProfile,
  fetchSourceSystems,
  profileSourceFile,
  type SourceFile,
  type SourceFileProfile,
  type SourceSystem,
  type UploadResult,
  uploadSourceFile,
} from "../api/sources";
import { ProfileView } from "./ProfileView";
import { getDemoUser } from "../api/context";
import {
  fetchIngestions,
  fetchMappings,
  ingestSourceFile,
  type IngestionSummary,
  type Mapping,
} from "../api/ingestion";
import { IngestionView } from "./IngestionView";

const MAX_UPLOAD_BYTES = Number(import.meta.env.VITE_MAX_UPLOAD_SIZE_BYTES ?? 250 * 1024 * 1024);
const MAX_UPLOAD_MIB = Math.floor(MAX_UPLOAD_BYTES / (1024 * 1024));

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function CsvUploadPage() {
  const canModify = getDemoUser() !== "viewer@demo.local";
  const inputRef = useRef<HTMLInputElement>(null);
  const [sourceSystems, setSourceSystems] = useState<SourceSystem[]>([]);
  const [sourceSystemCode, setSourceSystemCode] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [detail, setDetail] = useState<SourceFile | null>(null);
  const [profiles, setProfiles] = useState<Record<number, SourceFileProfile>>({});
  const [profileFile, setProfileFile] = useState<SourceFile | null>(null);
  const [ingestions, setIngestions] = useState<Record<number, IngestionSummary>>({});
  const [ingestionView, setIngestionView] = useState<IngestionSummary | null>(null);
  const [mappings, setMappings] = useState<Mapping[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: string; text: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      fetchSourceSystems(controller.signal),
      fetchSourceFiles(controller.signal),
      fetchMappings().catch(() => []),
    ])
      .then(([systems, recentFiles, loadedMappings]) => {
        setMappings(loadedMappings);
        setSourceSystems(systems);
        setSourceSystemCode(systems.find((system) => system.is_active)?.code ?? "");
        setFiles(recentFiles);
        void Promise.all(
          recentFiles.map(async (sourceFile) => {
            try {
              return [sourceFile.id, await fetchLatestProfile(sourceFile.id)] as const;
            } catch {
              return null;
            }
          }),
        ).then((entries) =>
          setProfiles(Object.fromEntries(entries.filter((entry) => entry !== null))),
        );
        void Promise.all(recentFiles.map(async (sourceFile) => {
          const history = await fetchIngestions(sourceFile.id);
          return history[0] ? [sourceFile.id, history[0]] as const : null;
        })).then((entries) => setIngestions(Object.fromEntries(entries.filter((entry) => entry !== null))));
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setMessage({ kind: "error", text: error instanceof Error ? error.message : "Load failed" });
      });
    return () => controller.abort();
  }, []);

  function chooseFile(file: File | undefined) {
    setMessage(null);
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setSelectedFile(null);
      setMessage({ kind: "error", text: "Choose a file with a .csv extension." });
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setSelectedFile(null);
      setMessage({
        kind: "error",
        text: `The CSV exceeds the ${MAX_UPLOAD_MIB} MiB upload limit.`,
      });
      return;
    }
    setSelectedFile(file);
  }

  async function runIngestion(sourceFile: SourceFile, forceRerun = false) {
    const mapping = mappings.find((item) => item.source_file_pattern.toLowerCase() === sourceFile.original_filename.toLowerCase());
    if (!mapping) { setMessage({ kind: "error", text: "No unambiguous active mapping matches this filename." }); return; }
    setBusy(true); setMessage(null);
    try { const result = await ingestSourceFile(sourceFile.id, mapping.mapping_code, forceRerun); setIngestions((current) => ({ ...current, [sourceFile.id]: result })); setIngestionView(result); }
    catch (error) { setMessage({ kind: "error", text: error instanceof Error ? error.message : "Ingestion failed." }); }
    finally { setBusy(false); }
  }

  async function submitUpload() {
    if (!selectedFile || !sourceSystemCode) return;
    setBusy(true);
    setMessage(null);
    try {
      const result: UploadResult = await uploadSourceFile(selectedFile, sourceSystemCode);
      if (result.status === "duplicate") {
        setMessage({
          kind: "duplicate",
          text: result.message ?? "This exact file has already been registered.",
        });
      } else {
        setMessage({ kind: "success", text: "CSV registered in immutable raw storage." });
        setSelectedFile(null);
        if (inputRef.current) inputRef.current.value = "";
      }
      setFiles(await fetchSourceFiles());
    } catch (error) {
      setMessage({
        kind: "error",
        text: error instanceof Error ? error.message : "The upload failed.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function showDetail(sourceFileId: number) {
    try {
      setDetail(await fetchSourceFile(sourceFileId));
    } catch (error) {
      setMessage({
        kind: "error",
        text: error instanceof Error ? error.message : "Could not load file details.",
      });
    }
  }

  async function runProfile(sourceFile: SourceFile) {
    setBusy(true);
    setMessage(null);
    try {
      const profile = await profileSourceFile(sourceFile.id);
      setProfiles((current) => ({ ...current, [sourceFile.id]: profile }));
      setProfileFile(sourceFile);
      setMessage({ kind: "success", text: "CSV profiling completed and results were saved." });
    } catch (error) {
      setMessage({
        kind: "error",
        text: error instanceof Error ? error.message : "Profiling failed.",
      });
    } finally {
      setBusy(false);
    }
  }

  if (profileFile && profiles[profileFile.id]) {
    return (
      <ProfileView
        sourceFile={profileFile}
        profile={profiles[profileFile.id]}
        busy={busy}
        onClose={() => setProfileFile(null)}
        onRerun={() => void runProfile(profileFile)}
      />
    );
  }
  if (ingestionView) return <IngestionView ingestion={ingestionView} onClose={() => setIngestionView(null)} />;

  return (
    <section className="upload-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 2A–4 · Registration, profiling, and ingestion</p>
          <h2>Upload a CSV source file</h2>
          <p>
            Register untouched source bytes with a SHA-256 checksum. CSV contents are not
            modified. Profiling analyzes a read-only copy before ingestion.
          </p>
        </div>
        <span className="immutable-badge">Immutable raw storage</span>
      </div>

      <div className="upload-controls">
        <label>
          Source system
          <select
            value={sourceSystemCode}
            onChange={(event) => setSourceSystemCode(event.target.value)}
            disabled={busy || !canModify}
          >
            <option value="">Select a source system</option>
            {sourceSystems.map((system) => (
              <option key={system.id} value={system.code} disabled={!system.is_active}>
                {system.name}
              </option>
            ))}
          </select>
        </label>

        <div
          className="drop-zone"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            chooseFile(event.dataTransfer.files[0]);
          }}
        >
          <strong>Drop a CSV here</strong>
          <span>or choose a file up to {MAX_UPLOAD_MIB} MiB</span>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => chooseFile(event.target.files?.[0])}
          disabled={busy || !canModify}
          />
        </div>

        {selectedFile && (
          <div className="selected-file">
            <span>{selectedFile.name}</span>
            <strong>{formatBytes(selectedFile.size)}</strong>
          </div>
        )}

        {message && <p className={`upload-message ${message.kind}`}>{message.text}</p>}

        <button
          type="button"
          onClick={() => void submitUpload()}
        disabled={!selectedFile || !sourceSystemCode || busy || !canModify}
        >
          {busy ? "Registering…" : "Upload and register"}
        </button>
      </div>

      <div className="recent-heading">
        <h3>Recent source files</h3>
        <span>{files.length} shown</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Filename</th>
              <th>Source system</th>
              <th>Size</th>
              <th>Checksum</th>
              <th>Status</th>
              <th>Profile</th>
              <th>Profiled</th>
              <th>Warnings</th>
              <th>Errors</th>
              <th>Ingestion</th>
              <th>Accepted / rejected</th>
              <th>Uploaded</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {files.length === 0 ? (
              <tr>
                <td colSpan={13} className="empty-row">No CSV files registered yet.</td>
              </tr>
            ) : (
              files.map((sourceFile) => (
                <tr key={sourceFile.id}>
                  <td>{sourceFile.original_filename}</td>
                  <td>{sourceFile.source_system_code}</td>
                  <td>{formatBytes(sourceFile.file_size_bytes)}</td>
                  <td><code>{sourceFile.sha256_checksum.slice(0, 10)}…</code></td>
                  <td><span className="file-status">{sourceFile.status}</span></td>
                  <td>{profiles[sourceFile.id]?.status ?? "Not profiled"}</td>
                  <td>{profiles[sourceFile.id] ? new Date(profiles[sourceFile.id].generated_at).toLocaleString() : "—"}</td>
                  <td>{profiles[sourceFile.id]?.issue_totals.warning ?? 0}</td>
                  <td>{(profiles[sourceFile.id]?.issue_totals.error ?? 0) + (profiles[sourceFile.id]?.issue_totals.critical ?? 0)}</td>
                  <td>{ingestions[sourceFile.id]?.status ?? "Not ingested"}</td>
                  <td>{ingestions[sourceFile.id] ? `${ingestions[sourceFile.id].records_accepted} / ${ingestions[sourceFile.id].records_rejected}` : "—"}</td>
                  <td>{new Date(sourceFile.registered_at).toLocaleString()}</td>
                  <td>
                    <button className="text-button" type="button" onClick={() => void showDetail(sourceFile.id)}>
                      Details
                    </button>
                    {" · "}
                    <button
                      className="text-button"
                      type="button"
                    disabled={busy || (!profiles[sourceFile.id] && !canModify)}
                      onClick={() =>
                        profiles[sourceFile.id]
                          ? setProfileFile(sourceFile)
                          : void runProfile(sourceFile)
                      }
                    >
                      {profiles[sourceFile.id] ? "View profile" : "Profile"}
                    </button>
                    {" · "}
                    <button className="text-button" type="button" disabled={busy || !canModify || !profiles[sourceFile.id] || profiles[sourceFile.id].status === "blocked" || !mappings.some((item) => item.source_file_pattern.toLowerCase() === sourceFile.original_filename.toLowerCase())} title={!profiles[sourceFile.id] ? "Profile this file first" : !canModify ? "Your role cannot ingest" : "Ingest raw rows into source-specific staging"} onClick={() => ingestions[sourceFile.id] ? setIngestionView(ingestions[sourceFile.id]) : void runIngestion(sourceFile)}>{ingestions[sourceFile.id] ? "View ingestion" : "Ingest"}</button>
                    {ingestions[sourceFile.id] && canModify && <><span>{" · "}</span><button className="text-button" type="button" disabled={busy} onClick={() => void runIngestion(sourceFile, true)}>Rerun</button></>}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {detail && (
        <aside className="detail-card">
          <button className="close-button" type="button" onClick={() => setDetail(null)}>Close</button>
          <p className="eyebrow">Source file #{detail.id}</p>
          <h3>{detail.original_filename}</h3>
          <dl>
            <div><dt>Stored as</dt><dd>{detail.stored_filename}</dd></div>
            <div><dt>Relative path</dt><dd>{detail.relative_path}</dd></div>
            <div><dt>SHA-256</dt><dd><code>{detail.sha256_checksum}</code></dd></div>
          </dl>
        </aside>
      )}
    </section>
  );
}
