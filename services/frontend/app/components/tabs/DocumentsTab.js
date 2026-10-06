"use client";

import { StatusPill, STRINGS } from "../../lib";
import { SearchBar, Toolbar } from "../controls";
import { docTypeLabel } from "../shared";

export default function DocumentsTab({ documents, total, query, onQueryChange, error, loading, refresh, onNext, onPrev, hasNext, hasPrev, page, onDelete, deletingId }) {
  // Liste: job+tur basina SON surum; eski surumler yalnizca detay sayfasinda.
  // Arama backend'de (?q=).
  const rows = (documents || []).filter((d) => d.is_latest);
  return (
    <div className="panel">
      <Toolbar label={STRINGS.docsToolbar} onRefresh={refresh} count={rows?.length} />
      <SearchBar value={query} onChange={onQueryChange} />
      {error && <div className="error-banner">{error}</div>}
      <table className="responsive table-fixed documents-table">
        <thead>
          <tr>
            <th>{STRINGS.colType}</th>
            <th>{STRINGS.colJob}</th>
            <th>{STRINGS.colApplication}</th>
            <th>{STRINGS.colFile}</th>
            <th>{STRINGS.colActions}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((document) => (
            <tr key={document.id}>
              <td data-label={STRINGS.colType} className="cell-main">
                <div className="cell-title">
                  {docTypeLabel(document.type)}
                  <span className="lang-badge">{document.language.toUpperCase()}</span>
                  {document.is_latest && <span className="latest-badge">{STRINGS.latestBadge}</span>}
                </div>
              </td>
              <td data-label={`${STRINGS.colCompany} · ${STRINGS.colJob}`} className="cell-main">
                <div className="cell-title" title={`${document.company} — ${document.job_title}`}>
                  {document.company} — {document.job_title}
                </div>
              </td>
              <td data-label={STRINGS.colApplication} className="cell-main">
                {document.application ? (
                  <a className="link" href={`/applications/${document.application.id}`}>
                    <StatusPill status={document.application.status} />
                  </a>
                ) : (
                  <span className="muted">{STRINGS.unlinked}</span>
                )}
              </td>
              <td data-label={STRINGS.colFile} className="document-actions">
                <a
                  className="link"
                  href={document.view_url}
                  target="_blank"
                  rel="noreferrer"
                  title={`${STRINGS.viewFile} • ${document.created_at || ""}`}
                >
                  {STRINGS.viewFile}
                </a>
              </td>
              <td data-label={STRINGS.colActions} className="document-actions actions-sticky">
                <button
                  type="button"
                  className="danger-btn"
                  aria-label={`${STRINGS.deleteBtn}: ${document.type} ${document.language}`}
                  title={STRINGS.deleteBtn}
                  onClick={() => onDelete && onDelete(document)}
                  disabled={deletingId === document.id}
                >
                  {deletingId === document.id ? STRINGS.deleting : STRINGS.deleteBtn}
                </button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={5} className="muted">{loading ? STRINGS.loading : STRINGS.noDocumentsYet}</td></tr>
          )}
        </tbody>
      </table>
      <div className="toolbar" style={{ marginTop: 8 }}>
        <button className="refresh-btn" onClick={onPrev} disabled={!hasPrev}>
          {STRINGS.prevPage}
        </button>
        <span className="muted">{(STRINGS.pageIndicator || "Page {page}").replace("{page}", page || 1)}{typeof total === "number" ? ` • ${total}` : ""}</span>
        <button className="refresh-btn" onClick={onNext} disabled={!hasNext}>
          {STRINGS.nextPage}
        </button>
      </div>
    </div>
  );
}
