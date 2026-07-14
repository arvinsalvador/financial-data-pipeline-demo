import type { ServiceState } from "../api/health";

interface StatusCardProps {
  label: string;
  status: ServiceState;
}

export function StatusCard({ label, status }: StatusCardProps) {
  return (
    <article className={`status-card status-${status}`}>
      <span className="status-dot" aria-hidden="true" />
      <div>
        <p>{label}</p>
        <strong>{status}</strong>
      </div>
    </article>
  );
}
