"use client";

import { useEffect, useState, useCallback } from "react";
import { fetchJson, formatDate, StatusPill } from "./lib";

const TABS = ["Overview", "Jobs", "Documents", "Applications", "Events", "Settings"];
const REFRESH_MS = 10000;

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

const ACTIONS = [
  { id: "discover", label: "Search Jobs", description: "Search all sources for new listings." },
  { id: "match", label: "Run Matching", description: "Match new listings against your profile." },
  { id: "generate_documents", label: "Generate CV & Cover Letter", description: "Generate documents for qualifying listings." },
  { id: "analyze_applications", label: "Analyze Forms", description: "Inspect application forms for listings with ready documents." },
  { id: "fill_applications", label: "Fill Forms", description: "Fill ready applications; never submits." },
];

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
  return (
    <div className="panel">
      <Toolbar label="Discovered / matched jobs" onRefresh={refresh} count={jobs?.length} />
      {error && <div className="error-banner">{error}</div>}
      <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Company</th>
            <th>Title</th>
            <th>Source</th>
            <th>Location</th>
            <th>Remote</th>
            <th>Status</th>
            <th>Score</th>
            <th>Result</th>
            <th>Documents</th>
            <th>Discovered</th>
            <th>Link</th>
          </tr>
        </thead>
        <tbody>
          {(jobs || []).map((j) => (
            <tr key={j.id}>
              <td>{j.company}</td>
              <td>{j.title}</td>
              <td>{j.source}</td>
              <td>{j.location || "-"}</td>
              <td>{j.remote_status || "-"}</td>
              <td><StatusPill status={j.status} /></td>
              <td>{j.match_score ?? "-"}</td>
              <td>{j.qualification_status || "-"}</td>
              <td>{j.document_count ?? 0}</td>
              <td>{formatDate(j.created_at)}</td>
              <td>
                <a className="link" href={j.url} target="_blank" rel="noreferrer">
                  View
                </a>
              </td>
            </tr>
          ))}
          {(!jobs || jobs.length === 0) && (
            <tr>
              <td colSpan={11} className="muted">
                {loading ? "Loading…" : "No jobs discovered yet."}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function ApplicationsTab({ applications, error, loading, refresh, onSubmit, submittingApplicationId }) {
  return (
    <div className="panel">
      <Toolbar label="Application history" onRefresh={refresh} count={applications?.length} />
      {error && <div className="error-banner">{error}</div>}
      <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Job ID</th>
            <th>Status</th>
            <th>Mode</th>
            <th>Attempts</th>
            <th>Blocked Reason</th>
            <th>Failure Reason</th>
            <th>Created</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {(applications || []).map((a) => (
            <tr key={a.id}>
              <td>{a.job_id.slice(0, 8)}…</td>
              <td><StatusPill status={a.status} /></td>
              <td>{a.automation_mode}</td>
              <td>{a.attempts}</td>
              <td title={a.blocked_reason || ""}>{a.blocked_reason || "-"}</td>
              <td title={a.failure_reason || ""}>{a.failure_reason || "-"}</td>
              <td>{formatDate(a.created_at)}</td>
              <td className="actions-cell application-actions">
                <a
                  className="link"
                  href={a.application_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open in Browser
                </a>
                <a
                  className="link"
                  href={`ai-job-agent://prepare?application_id=${a.id}`}
                >
                  Fill with Playwright
                </a>
                <button
                  className="refresh-btn primary-btn"
                  disabled={Boolean(submittingApplicationId)}
                  onClick={() => onSubmit(a)}
                >
                  {submittingApplicationId === a.id ? "Submitting…" : "Submit with Playwright"}
                </button>
              </td>
            </tr>
          ))}
          {(!applications || applications.length === 0) && (
            <tr>
              <td colSpan={8} className="muted">
                {loading ? "Loading…" : "No applications yet."}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function DocumentsTab({ documents, error, loading, refresh }) {
  return (
    <div className="panel">
      <Toolbar label="Generated CVs and cover letters" onRefresh={refresh} count={documents?.length} />
      {error && <div className="error-banner">{error}</div>}
      <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Document</th>
            <th>Job</th>
            <th>Language</th>
            <th>Version</th>
            <th>Created</th>
            <th>Open</th>
          </tr>
        </thead>
        <tbody>
          {(documents || []).map((document) => (
            <tr key={document.id}>
              <td>{document.metadata?.filename || `${document.type === "cover_letter" ? "Cover Letter" : "CV"} (${document.language.toUpperCase()} v${document.version})`}</td>
              <td>{document.metadata?.company || document.job_id.slice(0, 8)}</td>
              <td>{document.language.toUpperCase()}</td>
              <td>{document.version}</td>
              <td>{formatDate(document.created_at)}</td>
              <td className="actions-cell document-actions">
                <a className="link" href={document.download_url} target="_blank" rel="noreferrer">
                  Open
                </a>
                <a className="link" href={document.download_url} download>
                  Download
                </a>
              </td>
            </tr>
          ))}
          {(!documents || documents.length === 0) && (
            <tr><td colSpan={6} className="muted">{loading ? "Loading…" : "No documents generated yet."}</td></tr>
          )}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function EventsTable({ events, loading }) {
  return (
    <div className="table-scroll">
    <table>
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
            <td>{e.event_type}</td>
            <td>{(e.entity_id || "").slice(0, 8)}…</td>
            <td>{e.correlation_id}</td>
            <td>{formatDate(e.timestamp)}</td>
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
    </div>
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
  const statusQ = usePolling("/api/v1/status");
  const jobsQ = usePolling("/api/v1/jobs?limit=100");
  const applicationsQ = usePolling("/api/v1/applications?limit=100");
  const documentsQ = usePolling("/api/v1/documents?limit=100");
  const eventsQ = usePolling("/api/v1/events?limit=50");

  const runAction = useCallback(async (action) => {
    const requiresExtraWarning = action.id === "fill_applications";
    const prompt = requiresExtraWarning
      ? "Application forms will be filled. The process stops on CAPTCHA, MFA, ambiguous questions, or submission; nothing is submitted while AUTO_SUBMIT is off. Continue?"
      : `Start "${action.label}"?`;
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
    if (!window.confirm(
      `Playwright will fill the form for ${name} and press submit. `
      + "The process stops on CAPTCHA, MFA, sign-in requirements, or unverified legal questions. Continue?"
    )) return;

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
        <HealthBadges health={health} />
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
