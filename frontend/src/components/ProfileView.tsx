import { useEffect, useState } from "react";

import {
  fetchProfileColumns,
  fetchProfileIssues,
  type ColumnProfile,
  type DataQualityIssue,
  type SourceFile,
  type SourceFileProfile,
} from "../api/sources";
import { getDemoUser } from "../api/context";

interface Props {
  sourceFile: SourceFile;
  profile: SourceFileProfile;
  busy: boolean;
  onClose: () => void;
  onRerun: () => void;
}

const money = (value: string | null) => (value === null ? "—" : value);

export function ProfileView({ sourceFile, profile, busy, onClose, onRerun }: Props) {
  const canRerun = getDemoUser() !== "viewer@demo.local";
  const [columns, setColumns] = useState<ColumnProfile[]>([]);
  const [issues, setIssues] = useState<DataQualityIssue[]>([]);
  const [severity, setSeverity] = useState("");
  const [issueType, setIssueType] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([
      fetchProfileColumns(profile.id),
      fetchProfileIssues(profile.id, severity, issueType),
    ])
      .then(([columnRows, issueRows]) => {
        setColumns(columnRows);
        setIssues(issueRows);
        setError(null);
      })
      .catch((requestError: unknown) =>
        setError(requestError instanceof Error ? requestError.message : "Profile load failed"),
      );
  }, [profile.id, severity, issueType]);

  return (
    <section className="profile-view">
      <div className="profile-toolbar">
        <div>
          <p className="eyebrow">Phase 2B · Profile #{profile.id}</p>
          <h2>{sourceFile.original_filename}</h2>
          <p><code>{sourceFile.sha256_checksum.slice(0, 12)}…</code> · {sourceFile.source_system_code}</p>
        </div>
        <div className="button-row">
          <button type="button" className="secondary-button" onClick={onClose}>Back to files</button>
          <button
            type="button"
            disabled={busy || !canRerun}
            onClick={() => {
              if (window.confirm("Rerun this profile version? Existing derived results will be refreshed.")) onRerun();
            }}
          >{busy ? "Profiling…" : "Rerun profiling"}</button>
        </div>
      </div>
      {error && <p className="upload-message error">{error}</p>}
      <div className="metric-grid">
        {[
          ["Status", profile.status], ["Version", profile.profile_version],
          ["Rows", profile.row_count], ["Columns", profile.column_count],
          ["File size", `${profile.file_size_bytes.toLocaleString()} bytes`],
          ["Encoding", profile.encoding ?? "—"], ["Delimiter", profile.delimiter ?? "—"],
          ["Duplicate rows", profile.duplicate_row_count], ["Empty rows", profile.empty_row_count],
          ["Null values", profile.total_null_count],
          ["Date range", profile.date_range_start ? `${profile.date_range_start} – ${profile.date_range_end}` : "—"],
          ["Amount total", money(profile.monetary_total)], ["Debit total", money(profile.debit_total)],
          ["Credit total", money(profile.credit_total)], ["Opening balance", money(profile.opening_balance)],
          ["Closing balance", money(profile.closing_balance)],
          ["Calculated close", money(profile.calculated_closing_balance)],
          ["Running balance", profile.running_balance_valid === null ? "Not verifiable" : profile.running_balance_valid ? "Valid" : "Invalid"],
          ["Info", profile.issue_totals.info ?? 0], ["Warnings", profile.issue_totals.warning ?? 0],
          ["Errors", profile.issue_totals.error ?? 0], ["Critical", profile.issue_totals.critical ?? 0],
        ].map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}
      </div>

      <h3>Column profiles</h3>
      <div className="table-wrap profile-table"><table><thead><tr>
        <th>Column</th><th>Type</th><th>Nulls</th><th>Null %</th><th>Unique</th><th>Min</th><th>Max</th><th>Date range</th><th>Samples</th>
      </tr></thead><tbody>{columns.map((column) => <tr key={column.id}>
        <td>{column.column_name}</td><td>{column.inferred_data_type}</td><td>{column.null_count}</td>
        <td>{Number(column.null_percentage).toFixed(2)}%</td><td>{column.unique_count}</td>
        <td>{column.minimum_value ?? "—"}</td><td>{column.maximum_value ?? "—"}</td>
        <td>{column.earliest_date ? `${column.earliest_date} – ${column.latest_date}` : "—"}</td>
        <td>{column.sample_values_json?.join(", ") || "—"}</td>
      </tr>)}</tbody></table></div>

      <div className="issue-heading"><h3>Data-quality issues</h3><div className="filters">
        <label>Severity<select value={severity} onChange={(event) => setSeverity(event.target.value)}>
          <option value="">All</option><option>info</option><option>warning</option><option>error</option><option>critical</option>
        </select></label>
        <label>Type<select value={issueType} onChange={(event) => setIssueType(event.target.value)}>
          <option value="">All</option>{[...new Set(issues.map((issue) => issue.issue_type))].map((value) => <option key={value}>{value}</option>)}
        </select></label>
      </div></div>
      <div className="table-wrap"><table><thead><tr>
        <th>Severity</th><th>Code</th><th>Type</th><th>Column</th><th>Row</th><th>Message</th><th>Observed</th><th>Status</th>
      </tr></thead><tbody>{issues.length ? issues.map((issue) => <tr key={issue.id}>
        <td><span className={`severity ${issue.severity}`}>{issue.severity}</span></td><td>{issue.issue_code}</td>
        <td>{issue.issue_type}</td><td>{issue.column_name ?? "—"}</td><td>{issue.row_number ?? "—"}</td>
        <td>{issue.message}</td><td>{issue.observed_value ?? "—"}</td><td>{issue.status}</td>
      </tr>) : <tr><td colSpan={8} className="empty-row">No issues match these filters.</td></tr>}</tbody></table></div>
    </section>
  );
}
