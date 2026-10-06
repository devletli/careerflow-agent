"use client";

import { useState } from "react";
import { fetchJson, formatDate, StatusPill, STRINGS } from "../../lib";
import { SearchBar, Toolbar } from "../controls";

const SOURCES = ["bundesagentur", "arbeitnow", "workable", "greenhouse", "lever", "ashby", "smartrecruiters", "manual"];
const BANDS = ["QUALIFIED", "REVIEW", "NOT_QUALIFIED"];

function isNew(createdAt) {
  if (!createdAt) return false;
  return Date.now() - new Date(createdAt).getTime() < 7 * 24 * 3600 * 1000;
}

function ExplainCell({ job }) {
  const [text, setText] = useState(job.match_explanation || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const needsExplain = !text || text.startsWith("Overall Match Score:");
  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const res = await fetchJson(`/api/v1/jobs/${job.id}/explain`, { method: "POST" });
      setText(res.explanation || "");
    } catch (e) {
      setError(STRINGS.explainFailed);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="cell-sub">
      {job.qualification_status || ""}
      {text && !needsExplain && <div title={text}>{text.slice(0, 120)}</div>}
      {needsExplain && job.match_score != null && (
        <button className="refresh-btn" onClick={run} disabled={busy}>
          {busy ? STRINGS.explaining : STRINGS.explainBtn}
        </button>
      )}
      {error && <div className="error-banner">{error}</div>}
    </div>
  );
}

export default function JobsTab({
  jobs, jobsMeta, query, onQueryChange,
  minScore, onMinScoreChange, band, onBandChange, source, onSourceChange,
  onlyNew, onOnlyNewChange,
  error, loading, refresh,
  onNext, onPrev, hasNext, hasPrev, page,
  onDelete, deletingId, onArchive, archivingId, hideArchived, onHideArchivedChange,
}) {
  // Backend already filters ARCHIVED when ?exclude_archived=true; keep a
  // defensive client filter for cached/polling overlap.
  const all = jobs || [];
  const rows = hideArchived ? all.filter((j) => j.user_status !== "ARCHIVED") : all;
  const meta = jobsMeta || { total: rows.length, scored: 0, unscored: 0 };
  const summary = (STRINGS.jobsSummary || "")
    .replace("{total}", meta.total ?? 0)
    .replace("{scored}", meta.scored ?? 0)
    .replace("{unscored}", meta.unscored ?? 0);
  return (
    <div className="panel">
      <Toolbar label={STRINGS.bestMatches || STRINGS.jobsToolbar} onRefresh={refresh} count={rows?.length} />
      <p className="muted">{summary}</p>
      <div className="toolbar">
        <SearchBar value={query} onChange={onQueryChange} />
        <label className="muted" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {STRINGS.minScoreFilter || STRINGS.minScore}
          <input
            type="range" min="0" max="100" step="5"
            value={minScore === "" ? 0 : Number(minScore)}
            onChange={(e) => onMinScoreChange && onMinScoreChange(e.target.value === "0" ? "" : e.target.value)}
            aria-label={STRINGS.minScoreFilter || STRINGS.minScore}
          />
          <span>{minScore === "" ? "–" : minScore}</span>
        </label>
        <label className="muted" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {STRINGS.bandFilter}
          <select value={band || ""} onChange={(e) => onBandChange && onBandChange(e.target.value)} aria-label={STRINGS.bandFilter}>
            <option value="">{STRINGS.allBands}</option>
            {BANDS.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        </label>
        <label className="muted" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {STRINGS.sourceFilter}
          <select value={source || ""} onChange={(e) => onSourceChange && onSourceChange(e.target.value)} aria-label={STRINGS.sourceFilter}>
            <option value="">{STRINGS.allSources}</option>
            {SOURCES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="muted" style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={Boolean(onlyNew)} onChange={(e) => onOnlyNewChange && onOnlyNewChange(e.target.checked)} />
          {STRINGS.onlyNew}
        </label>
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
                {isNew(j.created_at) && <span className="latest-badge">{STRINGS.newBadge}</span>}
              </td>
              <td data-label={STRINGS.colMatch} className="cell-main">
                <div className="cell-title">{j.match_score ?? STRINGS.unscoredBadge}</div>
                <ExplainCell job={j} />
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
      <div className="toolbar" style={{ marginTop: 8 }}>
        <button className="refresh-btn" onClick={onPrev} disabled={!hasPrev}>
          {STRINGS.prevPage}
        </button>
        <span className="muted">{(STRINGS.pageIndicator || "Page {page}").replace("{page}", page || 1)}</span>
        <button className="refresh-btn" onClick={onNext} disabled={!hasNext}>
          {STRINGS.nextPage}
        </button>
      </div>
    </div>
  );
}
