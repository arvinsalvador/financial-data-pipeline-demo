import { useEffect, useRef, useState } from "react";

import {
  fetchSourceFile,
  fetchSourceFiles,
  fetchSourceSystems,
  type SourceFile,
  type SourceSystem,
  type UploadResult,
  uploadSourceFile,
} from "../api/sources";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function CsvUploadPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [sourceSystems, setSourceSystems] = useState<SourceSystem[]>([]);
  const [sourceSystemCode, setSourceSystemCode] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [detail, setDetail] = useState<SourceFile | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: string; text: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      fetchSourceSystems(controller.signal),
      fetchSourceFiles(controller.signal),
    ])
      .then(([systems, recentFiles]) => {
        setSourceSystems(systems);
        setSourceSystemCode(systems.find((system) => system.is_active)?.code ?? "");
        setFiles(recentFiles);
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
      setMessage({ kind: "error", text: "The CSV exceeds the 10 MB upload limit." });
      return;
    }
    setSelectedFile(file);
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

  return (
    <section className="upload-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 2A · Source registration</p>
          <h2>Upload a CSV source file</h2>
          <p>
            Register untouched source bytes with a SHA-256 checksum. CSV contents are not
            parsed or ingested yet.
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
            disabled={busy}
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
          <span>or choose a file up to 10 MB</span>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => chooseFile(event.target.files?.[0])}
            disabled={busy}
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
          disabled={!selectedFile || !sourceSystemCode || busy}
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
              <th>Uploaded</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {files.length === 0 ? (
              <tr>
                <td colSpan={7} className="empty-row">No CSV files registered yet.</td>
              </tr>
            ) : (
              files.map((sourceFile) => (
                <tr key={sourceFile.id}>
                  <td>{sourceFile.original_filename}</td>
                  <td>{sourceFile.source_system_code}</td>
                  <td>{formatBytes(sourceFile.file_size_bytes)}</td>
                  <td><code>{sourceFile.sha256_checksum.slice(0, 10)}…</code></td>
                  <td><span className="file-status">{sourceFile.status}</span></td>
                  <td>{new Date(sourceFile.registered_at).toLocaleString()}</td>
                  <td>
                    <button className="text-button" type="button" onClick={() => void showDetail(sourceFile.id)}>
                      Details
                    </button>
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
