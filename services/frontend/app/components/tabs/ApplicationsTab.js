"use client";

import { useState } from "react";
import { formatDate, StatusPill, STRINGS } from "../../lib";
import { distinctStatuses, SearchBar, Toolbar } from "../controls";
import { DocBadges, UrlAddDialog } from "../shared";

export default function ApplicationsTab({ applications, total, query, onQueryChange, statusFilter, onStatusChange, minScore, onMinScoreChange, error, loading, refresh, onNext, onPrev, hasNext, hasPrev, page, onExecute, busyId, onDelete }) {
  // Filtreleme backend'de (?q=&status=&min_score=); burada yalnızca yanıt render edilir.
  const rows = applications || [];
  const [dialogOpen, setDialogOpen] = useState(false);
  const [notice, setNotice] = useState("");
  // Available actions per application status (P0). Legacy backend
  // statuses are normalized so no row ever shows a wrong action set.
  function getAvailableActions(application) {
    switch (application.status) {
      case "CREATED":
        return ["prepare"];
      case "READY_TO_SUBMIT":
      case "READY_TO_APPLY":
        return ["submit"];
      case "RUNNING":
      case "FILLING":
      case "SUBMITTING":
        return ["view"];
      case "REQUIRES_HUMAN":
      case "BLOCKED":
        return ["continue"];
      case "FAILED":
        return ["retry"];
      case "SUBMITTED":
        return ["details"];
      default:
        return [];
    }
  }

  return (
    <div className="panel">
      <Toolbar label={STRINGS.appHistory} onRefresh={refresh} count={rows?.length} />
      <div className="toolbar">
        <button className="refresh-btn primary-btn" onClick={() => setDialogOpen(true)}>
          {STRINGS.addViaUrl}
        </button>
      </div>
      {notice && <div className="action-message">{notice}</div>}
      <SearchBar
        value={query}
        onChange={onQueryChange}
        statusValue={statusFilter}
        onStatusChange={onStatusChange}
        statuses={distinctStatuses(applications)}
        minScore={minScore}
        onMinScoreChange={onMinScoreChange}
        showScore
      />
      {error && <div className="error-banner">{error}</div>}
      <table className="responsive table-fixed applications-table">
        <thead>
          <tr>
            <th>{STRINGS.colJob}</th>
            <th>{STRINGS.colScore}</th>
            <th>{STRINGS.colStatus}</th>
            <th>{STRINGS.colDocs}</th>
            <th>{STRINGS.colUpdated}</th>
            <th>{STRINGS.colActions}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => {
            const actions = getAvailableActions(a);
            return (
            <tr key={a.id}>
              <td data-label={STRINGS.colJob} className="cell-main">
                <div className="cell-title" title={`${a.company} — ${a.title}`}>
                  <a className="link" href={`/applications/${a.id}`}>{a.company} — {a.title}</a>
                </div>
                <div className="cell-sub" title={a.blocked_reason || a.failure_reason || ""}>
                  {a.blocked_reason || a.failure_reason || `${a.automation_mode} • attempts: ${a.attempts}`}
                </div>
              </td>
              <td data-label={STRINGS.colScore} className="cell-main">
                <div className="cell-title">{a.match_score ?? "-"}</div>
              </td>
              <td data-label={STRINGS.colStatus}>
                <StatusPill status={a.status} />
                {a.lifecycle_status && (
                  <div className="cell-sub" title={a.next_action || ""}>
                    {a.lifecycle_status}{a.next_action_due_at ? ` • ${a.next_action_due_at.slice(0, 10)}` : ""}
                  </div>
                )}
              </td>
              <td data-label={STRINGS.colDocs}><DocBadges docs={a.documents} /></td>
              <td data-label={STRINGS.colUpdated} className="cell-wrap">{formatDate(a.created_at)}</td>
              <td data-label={STRINGS.colActions} className="application-actions actions-sticky">
                  {actions.includes("prepare") && (
                    <button className="refresh-btn" onClick={() => onExecute(a, "prepare")} disabled={busyId === a.id}>
                      {STRINGS.prepareBtn}
                    </button>
                  )}
                  {actions.includes("submit") && (
                    <button className="refresh-btn primary-btn" onClick={() => onExecute(a, "submit")} disabled={busyId === a.id}>
                      {STRINGS.submitBtn}
                    </button>
                  )}
                  {/* Retained: ai-job-agent://prepare is the desktop-runner entry
                      point, handled by scripts/desktop_runner.py. */}
                  {actions.includes("view") && (
                    <a className="link" href={`ai-job-agent://prepare?application_id=${a.id}`}>
                      {STRINGS.viewProgress}
                    </a>
                  )}
                  {actions.includes("continue") && (
                    <button className="refresh-btn" onClick={() => onExecute(a, "continue")} disabled={busyId === a.id}>
                      {STRINGS.continueManual}
                    </button>
                  )}
                  {actions.includes("retry") && (
                    <button className="refresh-btn" onClick={() => onExecute(a, "retry")} disabled={busyId === a.id}>
                      {STRINGS.retryBtn}
                    </button>
                  )}
                  {actions.includes("details") && (
                    <a className="link" href={`/applications/${a.id}`}>
                      {STRINGS.goToDetail}
                    </a>
                  )}
                  {/* destructive action: always separate, never via getAvailableActions */}
                  <button
                    type="button"
                    className="danger-btn"
                    aria-label={`${STRINGS.deleteBtn}: ${a.company} — ${a.title}`}
                    title={STRINGS.deleteBtn}
                    onClick={() => onDelete && onDelete(a)}
                    disabled={busyId === a.id}
                  >
                    {STRINGS.deleteBtn}
                  </button>
                </td>
            </tr>
            );
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                {loading ? STRINGS.loading : STRINGS.noApplications}
              </td>
            </tr>
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
      <UrlAddDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onAdded={(result) => {
          setDialogOpen(false);
          setNotice(`${result.application.id.slice(0, 8)}…`);
          refresh();
        }}
      />
    </div>
  );
}
