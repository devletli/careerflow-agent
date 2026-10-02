"use client";

import { useEffect, useState, useCallback } from "react";
import { fetchJson, formatDate, StatusPill, STRINGS } from "./lib";

const TABS = STRINGS.tabs;
const REFRESH_MS = 10000;
const THEME_KEY = "ai-job-agent-theme";

function useTheme() {
  const [theme, setTheme] = useState("light");

  useEffect(() => {
    setTheme(document.documentElement.dataset.theme || "light");
  }, []);

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch {
        // storage unavailable: theme still applies for this session
      }
      return next;
    });
  }, []);

  return { theme, toggle };
}

function ThemeToggle({ theme, onToggle }) {
  const isDark = theme === "dark";
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={onToggle}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      {isDark ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  );
}

function useHealth() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const data = await fetchJson("/health-check");
      setHealth(data);
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return { health, error };
}

function HealthBadges({ health }) {
  const deps = health?.dependencies || {};
  const names = ["postgres", "redis", "minio"];
  return (
    <div className="health-badges">
      <span className={`badge`}>
        <span className={`dot ${health ? (health.status === "ok" ? "ok" : "bad") : "unknown"}`} />
        API {health ? health.status : "unknown"}
      </span>
      {names.map((n) => (
        <span className="badge" key={n}>
          <span className={`dot ${n in deps ? (deps[n] ? "ok" : "bad") : "unknown"}`} />
          {n}
        </span>
      ))}
    </div>
  );
}

function usePolling(path, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const result = await fetchJson(path);
      setData(result);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, ...deps]);

  return { data, error, loading, refresh };
}

function Toolbar({ label, onRefresh, count }) {
  return (
    <div className="toolbar">
      <span className="muted">
        {label}
        {typeof count === "number" ? ` — ${count} shown` : ""}
      </span>
      <button className="refresh-btn" onClick={onRefresh}>
        Refresh
      </button>
    </div>
  );
}

function SearchBar({ value, onChange, statusValue, onStatusChange, statuses, minScore, onMinScoreChange, showScore }) {
  return (
    <div className="search-bar">
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={STRINGS.searchPlaceholder}
        aria-label={STRINGS.searchPlaceholder}
      />
      {statuses && (
        <select value={statusValue} onChange={(e) => onStatusChange(e.target.value)} aria-label={STRINGS.colStatus}>
          <option value="">{STRINGS.allStatuses}</option>
          {statuses.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      )}
      {showScore && (
        <label className="muted">
          {STRINGS.minScore}
          <input
            type="number"
            min="0"
            max="100"
            value={minScore}
            onChange={(e) => onMinScoreChange(e.target.value)}
            aria-label={STRINGS.minScore}
          />
        </label>
      )}
    </div>
  );
}

function distinctStatuses(rows) {
  return [...new Set((rows || []).map((r) => r.status).filter(Boolean))].sort();
}

const ACTIONS = STRINGS.actions;

function ActionPanel({ onRun, runningAction, actionMessage }) {
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>Pipeline Controls</h3>
      <p className="muted">Each action is queued and executed safely by the responsible worker.</p>
      {actionMessage && <div className="action-message">{actionMessage}</div>}
      <div className="action-grid">
        {ACTIONS.map((action) => (
          <div className="action-card" key={action.id}>
            <strong>{action.label}</strong>
            <span className="muted">{action.description}</span>
            <button
              className="refresh-btn primary-btn"
              disabled={Boolean(runningAction)}
              onClick={() => onRun(action)}
            >
              {runningAction === action.id ? "Queueing…" : action.label}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function OverviewTab({ status, jobs, applications, events, eventsLoading, onRun, runningAction, actionMessage }) {
  const jobCount = jobs?.length ?? 0;
  const appCount = applications?.length ?? 0;
  const submitted = (applications || []).filter((a) => a.status === "SUBMITTED").length;
  const blocked = (applications || []).filter((a) => a.status === "BLOCKED").length;

  return (
    <div>
      <ActionPanel onRun={onRun} runningAction={runningAction} actionMessage={actionMessage} />
      <div className="stat-grid">
        <div className="stat-card">
          <div className="value">{jobCount}</div>
          <div className="label">Recent Jobs</div>
        </div>
        <div className="stat-card">
          <div className="value">{appCount}</div>
          <div className="label">Recent Applications</div>
        </div>
        <div className="stat-card">
          <div className="value">{submitted}</div>
          <div className="label">Submitted</div>
        </div>
        <div className="stat-card">
          <div className="value">{blocked}</div>
          <div className="label">Blocked</div>
        </div>
      </div>
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Automation Configuration</h3>
        {status ? (
          <div className="settings-grid">
            <div className="settings-item">
              <div className="label">Automation Mode</div>
              <div className="value">{status.automation_mode}</div>
            </div>
            <div className="settings-item">
              <div className="label">Auto Submit</div>
              <div className="value">{String(status.auto_submit)}</div>
            </div>
            <div className="settings-item">
              <div className="label">Min Match Score</div>
              <div className="value">{status.min_match_score}</div>
            </div>
          </div>
        ) : (
          <p className="muted">Loading status…</p>
        )}
      </div>
      <div className="panel" style={{ marginTop: 16 }}>
        <h3 style={{ marginTop: 0 }}>Latest Pipeline Events</h3>
        <EventsTable events={(events || []).slice(0, 8)} loading={eventsLoading} />
      </div>
    </div>
  );
}

function JobsTab({ jobs, error, loading, refresh }) {
  const [query, setQuery] = useState("");
  const filtered = (jobs || []).filter((j) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return `${j.title || ""} ${j.company || ""} ${j.url || ""}`.toLowerCase().includes(q);
  });
  return (
    <div className="panel">
      <Toolbar label="Discovered / matched jobs" onRefresh={refresh} count={filtered?.length} />
      <SearchBar value={query} onChange={setQuery} />
      {error && <div className="error-banner">{error}</div>}
      <table className="responsive">
        <thead>
          <tr>
            <th>Job</th>
            <th>Location</th>
            <th>Status</th>
            <th>Match</th>
            <th>Docs</th>
            <th>Updated</th>
            <th>Link</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((j) => (
            <tr key={j.id}>
              <td data-label="Job" className="cell-main">
                <div className="cell-title" title={j.title}>{j.title}</div>
                <div className="cell-sub" title={`${j.company} • ${j.source}`}>{j.company} • {j.source}</div>
              </td>
              <td data-label="Location" className="cell-main">
                <div className="cell-title" title={j.location || "-"}>{j.location || "-"}</div>
                <div className="cell-sub">{j.remote_status || ""}</div>
              </td>
              <td data-label="Status"><StatusPill status={j.status} /></td>
              <td data-label="Match" className="cell-main">
                <div className="cell-title">{j.match_score ?? "-"}</div>
                <div className="cell-sub">{j.qualification_status || ""}</div>
              </td>
              <td data-label="Docs">{j.document_count ?? 0}</td>
              <td data-label="Updated" className="cell-wrap">{formatDate(j.created_at)}</td>
              <td data-label="Link">
                <a className="link" href={j.url} target="_blank" rel="noreferrer">
                  View
                </a>
              </td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={7} className="muted">
                {loading ? "Loading…" : "No jobs discovered yet."}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function UrlAddDialog({ open, onClose, onAdded }) {
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

function DocBadges({ docs }) {
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

function ApplicationsTab({ applications, error, loading, refresh, onSubmit, submittingApplicationId }) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [minScore, setMinScore] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const filtered = (applications || []).filter((a) => {
    const q = query.trim().toLowerCase();
    const matchesQ = !q || `${a.company || ""} ${a.title || ""}`.toLowerCase().includes(q);
    const matchesS = !statusFilter || a.status === statusFilter;
    const matchesScore = !minScore || (a.match_score ?? -1) >= Number(minScore);
    return matchesQ && matchesS && matchesScore;
  });
  // Determine available actions per application state
  const availableActions = useCallback(() => {
    const a = applications?.find(x => x.id === submittingApplicationId);
    if (!a) return {};
    const status = a.status;
    const actions: Record<string, string> = {};
    if (status === "CREATED") actions.prepare = "Prepare";
    if (status === "READY_TO_SUBMIT") actions.submit = "Submit";
    if (status === "RUNNING") actions.view = "View progress";
    if (status === "REQUIRES_HUMAN") actions.continue = "Continue manually";
    if (status === "FAILED") actions.retry = "Retry";
    if (status === "SUBMITTED") actions.details = "View details";
    return actions;
  }, [applications, submittingApplicationId]);
  const actions = availableActions();
  
  return (
    <div className="panel">
      <Toolbar label="Application history" onRefresh={refresh} count={filtered?.length} />
      <div className="toolbar">
        <button className="refresh-btn primary-btn" onClick={() => setDialogOpen(true)}>
          {STRINGS.addViaUrl}
        </button>
      </div>
      {notice && <div className="action-message">{notice}</div>}
      <SearchBar
        value={query}
        onChange={setQuery}
        statusValue={statusFilter}
        onStatusChange={setStatusFilter}
        statuses={distinctStatuses(applications)}
        minScore={minScore}
        onMinScoreChange={setMinScore}
        showScore
      />
      {error && <div className="error-banner">{error}</div>}
      <table className="responsive table-fixed">
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
          {filtered.map((a) => (
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
              <td data-label={STRINGS.colStatus}><StatusPill status={a.status} /></td>
              <td data-label={STRINGS.colDocs}><DocBadges docs={a.documents} /></td>
              <td data-label={STRINGS.colUpdated} className="cell-wrap">{formatDate(a.created_at)}</td>
              <td data-label={STRINGS.colActions} className="application-actions">
                {actions.prepare && (
                  <button className="refresh-btn" onClick={() => onSubmit(a)}>
                    {actions.prepare}
                  </button>
                )}
                {actions.submit && (
                  <button className="refresh-btn primary-btn" onClick={() => onSubmit(a)} disabled={Boolean(submittingApplicationId)}>
                    {actions.submit}
                  </button>
                )}
                {actions.view && (
                  <a className="link" href={`ai-job-agent://prepare?application_id=${a.id}`}>
                    {actions.view}
                  </a>
                )}
                {actions.continue && (
                  <button className="refresh-btn" onClick={() => onSubmit(a)}>
                    {actions.continue}
                  </button>
                )}
                {actions.retry && (
                  <button className="refresh-btn" onClick={() => onSubmit(a)}>
                    {actions.retry}
                  </button>
                )}
                {actions.details && (
                  <a className="link" href={`/applications/${a.id}`}>
                    {actions.details}
                  </a>
                )}
              </td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={6} className="muted">
                {loading ? "Loading…" : "No applications yet."}
              </td>
            </tr>
          )}
        </tbody>
      </table>
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

function docTypeLabel(type) {
  return type === "cover_letter" ? "CL" : "CV";
}

function DocumentsTab({ documents, error, loading, refresh }) {
  const [query, setQuery] = useState("");
  const filtered = (documents || []).filter((d) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return `${d.company || ""} ${d.job_title || ""} ${d.type || ""}`.toLowerCase().includes(q);
  });
  return (
    <div className="panel">
      <Toolbar label="Generated CVs and cover letters" onRefresh={refresh} count={filtered?.length} />
      <SearchBar value={query} onChange={setQuery} />
      {error && <div className="error-banner">{error}</div>}
      <table className="responsive">
        <thead>
          <tr>
            <th>{STRINGS.colType}</th>
            <th>{STRINGS.colJob}</th>
            <th>{STRINGS.colApplication}</th>
            <th>{STRINGS.colFile}</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((document) => (
            <tr key={document.id}>
              <td data-label={STRINGS.colType} className="cell-main">
                <div className="cell-title">
                  {docTypeLabel(document.type)}
                  <span className="lang-badge">{document.language.toUpperCase()}</span>
                  {document.is_latest && <span className="latest-badge">{STRINGS.latestBadge}</span>}
                </div>
                <div className="cell-sub" title={document.created_at}>
                  {document.created_at}
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
                  title={STRINGS.viewFile}
                >
                  {STRINGS.viewFile}
                </a>
              </td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr><td colSpan={4} className="muted">{loading ? "Loading…" : "No documents generated yet."}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function EventsTable({ events, loading }) {
  return (
    <table className="responsive">
      <thead>
        <tr>
          <th>Event Type</th>
          <th>Entity</th>
          <th>Correlation</th>
          <th>Timestamp</th>
        </tr>
      </thead>
      <tbody>
        {(events || []).map((e) => (
          <tr key={e.event_id}>
            <td data-label="Event Type">{e.event_type}</td>
            <td data-label="Entity">{(e.entity_id || "").slice(0, 8)}…</td>
            <td data-label="Correlation">{e.correlation_id}</td>
            <td data-label="Timestamp" className="cell-wrap">{formatDate(e.timestamp)}</td>
          </tr>
        ))}
        {(!events || events.length === 0) && (
          <tr>
            <td colSpan={4} className="muted">
              {loading ? "Loading…" : "No pipeline events recorded yet."}
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function EventsTab({ events, error, loading, refresh }) {
  return (
    <div className="panel">
      <Toolbar label="Pipeline event stream (monitor)" onRefresh={refresh} count={events?.length} />
      {error && <div className="error-banner">{error}</div>}
      <EventsTable events={events} loading={loading} />
    </div>
  );
}

function SettingsTab({ status }) {
  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>Runtime Settings</h3>
      <p className="muted">
        These values are read-only in the dashboard; change them via the <code>.env</code> file
        and restart the stack with <code>docker compose up -d</code>.
      </p>
      {status ? (
        <div className="settings-grid">
          <div className="settings-item">
            <div className="label">Service</div>
            <div className="value">{status.service}</div>
          </div>
          <div className="settings-item">
            <div className="label">Version</div>
            <div className="value">{status.version}</div>
          </div>
          <div className="settings-item">
            <div className="label">Automation Mode</div>
            <div className="value">{status.automation_mode}</div>
          </div>
          <div className="settings-item">
            <div className="label">Auto Submit</div>
            <div className="value">{String(status.auto_submit)}</div>
          </div>
          <div className="settings-item">
            <div className="label">Min Match Score</div>
            <div className="value">{status.min_match_score}</div>
          </div>
        </div>
      ) : (
        <p className="muted">Loading…</p>
      )}
    </div>
  );
}

export default function Home() {
  const [tab, setTab] = useState("Overview");
  const [runningAction, setRunningAction] = useState(null);
  const [actionMessage, setActionMessage] = useState("");
  const { health } = useHealth();
  const { theme, toggle } = useTheme();
  const statusQ = usePolling("/api/v1/status");
  const jobsQ = usePolling("/api/v1/jobs?limit=100");
  const applicationsQ = usePolling("/api/v1/applications?limit=100");
  const documentsQ = usePolling("/api/v1/documents?limit=100");
  const eventsQ = usePolling("/api/v1/events?limit=50");

  const runAction = useCallback(async (action) => {
    const requiresExtraWarning = action.id === "fill_applications";
    const prompt = requiresExtraWarning
      ? STRINGS.confirmFill
      : STRINGS.confirmStart.replace("{label}", action.label);
    if (!window.confirm(prompt)) return;

    setRunningAction(action.id);
    setActionMessage("");
    try {
      const result = await fetchJson("/api/v1/pipeline/actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action.id, confirmed: true }),
      });
      setActionMessage(`${action.label} queued (${result.correlation_id}).`);
      setTimeout(() => {
        jobsQ.refresh();
        applicationsQ.refresh();
        documentsQ.refresh();
        eventsQ.refresh();
      }, 1000);
    } catch (error) {
      setActionMessage(`Could not start ${action.label}: ${error.message}`);
    } finally {
      setRunningAction(null);
    }
  }, [applicationsQ, documentsQ, eventsQ, jobsQ]);

  const submitApplication = useCallback(async (application) => {
    const name = `${application.company} — ${application.title}`;
    if (!window.confirm(STRINGS.confirmSubmit.replace("{name}", name))) return;

    setRunningAction(application.id);
    setActionMessage("");
    try {
      const result = await fetchJson("/api/v1/pipeline/actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "submit_application",
          application_id: application.id,
          confirmed: true,
        }),
      });
      setActionMessage(`Submission for ${name} queued (${result.correlation_id}).`);
      setTimeout(() => {
        applicationsQ.refresh();
        eventsQ.refresh();
      }, 1000);
    } catch (error) {
      setActionMessage(`Could not start submission for ${name}: ${error.message}`);
    } finally {
      setRunningAction(null);
    }
  }, [applicationsQ, eventsQ]);

  return (
    <main className="app-shell">
      <div className="app-header">
        <h1>AI Job Agent</h1>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <HealthBadges health={health} />
          <ThemeToggle theme={theme} onToggle={toggle} />
        </div>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t}
            className={`tab ${tab === t ? "active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Overview" && (
        <OverviewTab
          status={statusQ.data}
          jobs={jobsQ.data}
          applications={applicationsQ.data}
          events={eventsQ.data}
          eventsLoading={eventsQ.loading}
          onRun={runAction}
          runningAction={runningAction}
          actionMessage={actionMessage}
        />
      )}
      {tab === "Jobs" && <JobsTab jobs={jobsQ.data} error={jobsQ.error} loading={jobsQ.loading} refresh={jobsQ.refresh} />}
      {tab === "Applications" && (
        <ApplicationsTab
          applications={applicationsQ.data}
          error={applicationsQ.error}
          loading={applicationsQ.loading}
          refresh={applicationsQ.refresh}
          onSubmit={submitApplication}
          submittingApplicationId={runningAction}
        />
      )}
      {tab === "Documents" && (
        <DocumentsTab
          documents={documentsQ.data}
          error={documentsQ.error}
          loading={documentsQ.loading}
          refresh={documentsQ.refresh}
        />
      )}
      {tab === "Events" && (
        <EventsTab events={eventsQ.data} error={eventsQ.error} loading={eventsQ.loading} refresh={eventsQ.refresh} />
      )}
      {tab === "Settings" && <SettingsTab status={statusQ.data} />}
    </main>
  );
}
