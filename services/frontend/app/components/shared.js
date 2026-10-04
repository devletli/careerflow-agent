"use client";

import { useState } from "react";
import { fetchJson, formatDate, STRINGS } from "../lib";

export function docTypeLabel(type) {
  return type === "cover_letter" ? "CL" : "CV";
}

export async function deleteResource(path) {
  return fetchJson(path, { method: "DELETE" });
}

export function ConfirmDeleteDialog({ open, title, message, onCancel, onConfirm, loading }) {
  if (!open) return null;
  return (
    <div className="modal-backdrop">
      <div className="modal" role="dialog" aria-modal="true">
        <h3>{title}</h3>
        <p className="muted">{message}</p>
        <div className="modal-actions">
          <button type="button" className="refresh-btn" onClick={onCancel} disabled={loading}>
            {STRINGS.cancelBtn || STRINGS.cancel}
          </button>
          <button type="button" className="danger-btn" onClick={onConfirm} disabled={loading}>
            {loading ? STRINGS.deleting : STRINGS.deleteBtn}
          </button>
        </div>
      </div>
    </div>
  );
}

export function formatLlmStatus(llm) {
  if (!llm || !llm.state) return STRINGS.statusUnknown;
  const model = llm.model ? ` (${llm.model})` : "";
  const reason = llm.reason ? ` — ${llm.reason}` : "";
  return `${llm.state}${model}${reason}`;
}

export function DocBadges({ docs }) {
  const latest = docs?.latest || [];
  if (!latest.length) return <span className="muted">-</span>;
  return (
    <span className="doc-badges">
      {latest.map((d) => (
        <a
          key={d.id}
          className="link doc-badge"
          href={`/api/v1/documents/${d.id}/file?download=0`}
          target="_blank"
          rel="noreferrer"
          title={`${d.type} (${d.language})`}
        >
          {d.type === "cover_letter" ? "CL" : "CV"}
          <span className="lang-badge">{d.language.toUpperCase()}</span>
        </a>
      ))}
    </span>
  );
}

export function UrlAddDialog({ open, onClose, onAdded }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  if (!open) return null;
  const submit = async () => {
    setBusy(true);
    setMessage("");
    try {
      const result = await fetchJson("/api/v1/applications/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      setUrl("");
      onAdded(result);
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="dialog-backdrop">
      <div className="dialog">
        <h3 style={{ marginTop: 0 }}>{STRINGS.urlDialogTitle}</h3>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={STRINGS.urlPlaceholder}
          aria-label={STRINGS.urlPlaceholder}
        />
        {message && <div className="error-banner">{message}</div>}
        <div className="application-actions">
          <button className="refresh-btn" onClick={onClose} disabled={busy}>
            {STRINGS.cancel}
          </button>
          <button className="refresh-btn primary-btn" onClick={submit} disabled={busy || !url.trim()}>
            {STRINGS.add}
          </button>
        </div>
      </div>
    </div>
  );
}

export function EventsTable({ events, loading }) {
  return (
    <table className="responsive">
      <thead>
        <tr>
          <th>{STRINGS.colEventType}</th>
          <th>{STRINGS.colEntity}</th>
          <th>{STRINGS.colCorrelation}</th>
          <th>{STRINGS.colTimestamp}</th>
        </tr>
      </thead>
      <tbody>
        {(events || []).map((e) => (
          <tr key={e.event_id}>
            <td data-label={STRINGS.colEventType}>{e.event_type}</td>
            <td data-label={STRINGS.colEntity}>{(e.entity_id || "").slice(0, 8)}…</td>
            <td data-label={STRINGS.colCorrelation}>{e.correlation_id}</td>
            <td data-label={STRINGS.colTimestamp} className="cell-wrap">{formatDate(e.timestamp)}</td>
          </tr>
        ))}
        {(!events || events.length === 0) && (
          <tr>
            <td colSpan={4} className="muted">
              {loading ? STRINGS.loading : STRINGS.noEventsYet}
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
