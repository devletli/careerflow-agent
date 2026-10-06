"use client";

import { formatDate, StatusPill, STRINGS } from "../../lib";
import { SearchBar, Toolbar } from "../controls";

export default function JobsTab({ jobs, query, onQueryChange, error, loading, refresh, onDelete, deletingId, onArchive, archivingId, hideArchived, onHideArchivedChange }) {
  // Backend already filters ARCHIVED when ?exclude_archived=true; keep a
  // defensive client filter for cached/polling overlap.
  const all = jobs || [];
  const rows = hideArchived ? all.filter((j) => j.user_status !== "ARCHIVED") : all;
  return (
    <div className="panel">
      <Toolbar label={STRINGS.jobsToolbar} onRefresh={refresh} count={rows?.length} />
      <div className="toolbar">
        <SearchBar value={query} onChange={onQueryChange} />
        <label className="muted" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={Boolean(hideArchived)} onChange={(e) => onHideArchivedChange && onHideArchivedChange(e.target.checked)} />
          {STRINGS.hideArchived}
        </label>
      </div>
      {error && <div className="error-banner">{error}</div>}
      <table className="responsive table-fixed jobs-table">
        <thead>
          <tr>
            <th>{STRINGS.colJob}</th>
            <th>{STRINGS.colLocation}</th>
            <th>{STRINGS.colStatus}</th>
            <th>{STRINGS.colMatch}</th>
            <th>{STRINGS.colDocs}</th>
            <th>{STRINGS.colUpdated}</th>
            <th>{STRINGS.colActions}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((j) => (
            <tr key={j.id}>
              <td data-label={STRINGS.colJob} className="cell-main">
                <div className="cell-title" title={j.title}>{j.title}</div>
                <div className="cell-sub" title={`${j.company} • ${j.source}`}>{j.company} • {j.source}</div>
              </td>
              <td data-label={STRINGS.colLocation} className="cell-main">
                <div className="cell-title" title={j.location || "-"}>{j.location || "-"}</div>
                <div className="cell-sub">{j.remote_status || ""}</div>
              </td>
              <td data-label={STRINGS.colStatus}>
                <StatusPill status={j.status} />
                {j.user_status && <div className="cell-sub">{j.user_status}</div>}
              </td>
              <td data-label={STRINGS.colMatch} className="cell-main">
                <div className="cell-title">{j.match_score ?? "-"}</div>
                <div className="cell-sub">{j.qualification_status || ""}</div>
              </td>
              <td data-label={STRINGS.colDocs}>{j.document_count ?? 0}</td>
              <td data-label={STRINGS.colUpdated} className="cell-wrap">{formatDate(j.created_at)}</td>
              <td data-label={STRINGS.colActions} className="actions-sticky">
                <a className="link" href={j.url} target="_blank" rel="noreferrer">
                  {STRINGS.viewLink}
                </a>
                {j.user_status === "ARCHIVED" ? (
                  <button
                    type="button"
                    className="refresh-btn"
                    aria-label={`${STRINGS.unarchive}: ${j.company} — ${j.title}`}
                    onClick={() => onArchive && onArchive(j, null)}
                    disabled={archivingId === j.id}
                  >
                    {STRINGS.unarchive}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="refresh-btn"
                    aria-label={`${STRINGS.archive}: ${j.company} — ${j.title}`}
                    onClick={() => onArchive && onArchive(j, "ARCHIVED")}
                    disabled={archivingId === j.id}
                  >
                    {STRINGS.archive}
                  </button>
                )}
                <button
                  type="button"
                  className="danger-btn"
                  aria-label={`${STRINGS.deleteBtn}: ${j.company} — ${j.title}`}
                  title={STRINGS.deleteBtn}
                  onClick={() => onDelete && onDelete(j)}
                  disabled={deletingId === j.id}
                >
                  {deletingId === j.id ? STRINGS.deleting : STRINGS.deleteBtn}
                </button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={7} className="muted">
                {loading ? STRINGS.loading : STRINGS.noJobs}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
