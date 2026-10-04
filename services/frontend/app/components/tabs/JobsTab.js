"use client";

import { formatDate, StatusPill, STRINGS } from "../../lib";
import { SearchBar, Toolbar } from "../controls";

export default function JobsTab({ jobs, query, onQueryChange, error, loading, refresh }) {
  // Filtreleme backend'de (?q=); burada yalnızca backend yanıtı render edilir.
  const rows = jobs || [];
  return (
    <div className="panel">
      <Toolbar label={STRINGS.jobsToolbar} onRefresh={refresh} count={rows?.length} />
      <SearchBar value={query} onChange={onQueryChange} />
      {error && <div className="error-banner">{error}</div>}
      <table className="responsive">
        <thead>
          <tr>
            <th>{STRINGS.colJob}</th>
            <th>{STRINGS.colLocation}</th>
            <th>{STRINGS.colStatus}</th>
            <th>{STRINGS.colMatch}</th>
            <th>{STRINGS.colDocs}</th>
            <th>{STRINGS.colUpdated}</th>
            <th>{STRINGS.colLink}</th>
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
              <td data-label={STRINGS.colStatus}><StatusPill status={j.status} /></td>
              <td data-label={STRINGS.colMatch} className="cell-main">
                <div className="cell-title">{j.match_score ?? "-"}</div>
                <div className="cell-sub">{j.qualification_status || ""}</div>
              </td>
              <td data-label={STRINGS.colDocs}>{j.document_count ?? 0}</td>
              <td data-label={STRINGS.colUpdated} className="cell-wrap">{formatDate(j.created_at)}</td>
              <td data-label={STRINGS.colLink}>
                <a className="link" href={j.url} target="_blank" rel="noreferrer">
                  {STRINGS.viewLink}
                </a>
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
