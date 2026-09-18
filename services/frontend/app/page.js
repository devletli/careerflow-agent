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
  { id: "discover", label: "İş Ara", description: "Tüm kaynaklarda yeni ilanları ara." },
  { id: "match", label: "Eşleştirme Çalıştır", description: "Yeni ilanları profilinle eşleştir." },
  { id: "generate_documents", label: "CV ve Mektup Üret", description: "Uygun ilanlar için belgeleri üret." },
  { id: "analyze_applications", label: "Formları Analiz Et", description: "Hazır belgeli ilanların başvuru formlarını incele." },
  { id: "fill_applications", label: "Formları Doldur", description: "Hazır başvuruları doldurur; gönderim yapmaz." },
];

function ActionPanel({ onRun, runningAction, actionMessage }) {
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>Pipeline Kontrolleri</h3>
      <p className="muted">Her işlem sıraya alınır ve ilgili worker tarafından güvenli biçimde yürütülür.</p>
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
              {runningAction === action.id ? "Sıraya alınıyor…" : action.label}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function OverviewTab({ status, jobs, applications, events, onRun, runningAction, actionMessage }) {
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
        <EventsTable events={(events || []).slice(0, 8)} />
      </div>
    </div>
  );
}

function JobsTab({ jobs, error, refresh }) {
  return (
    <div className="panel">
      <Toolbar label="Discovered / matched jobs" onRefresh={refresh} count={jobs?.length} />
      {error && <div className="error-banner">{error}</div>}
      <table>
        <thead>
          <tr>
            <th>Company</th>
            <th>Title</th>
            <th>Source</th>
            <th>Location</th>
            <th>Remote</th>
            <th>Status</th>
            <th>Skor</th>
            <th>Sonuç</th>
            <th>Belgeler</th>
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
                  view
                </a>
              </td>
            </tr>
          ))}
          {(!jobs || jobs.length === 0) && (
            <tr>
              <td colSpan={11} className="muted">
                No jobs discovered yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ApplicationsTab({ applications, error, refresh, onSubmit, submittingApplicationId }) {
  return (
    <div className="panel">
      <Toolbar label="Application history" onRefresh={refresh} count={applications?.length} />
      {error && <div className="error-banner">{error}</div>}
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
              <td>{a.blocked_reason || "-"}</td>
              <td>{a.failure_reason || "-"}</td>
              <td>{formatDate(a.created_at)}</td>
              <td className="application-actions">
                <a
                  className="link"
                  href={a.application_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Tarayıcıda Aç
                </a>
                <a
                  className="link"
                  href={`ai-job-agent://prepare?application_id=${a.id}`}
                >
                  Playwright ile Doldur
                </a>
                <button
                  className="refresh-btn primary-btn"
                  disabled={Boolean(submittingApplicationId)}
                  onClick={() => onSubmit(a)}
                >
                  {submittingApplicationId === a.id ? "Gönderiliyor…" : "Playwright ile Gönder"}
                </button>
              </td>
            </tr>
          ))}
          {(!applications || applications.length === 0) && (
            <tr>
              <td colSpan={8} className="muted">
                No applications yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function DocumentsTab({ documents, error, refresh }) {
  return (
    <div className="panel">
      <Toolbar label="Üretilen CV ve mektuplar" onRefresh={refresh} count={documents?.length} />
      {error && <div className="error-banner">{error}</div>}
      <table>
        <thead>
          <tr>
            <th>Tür</th>
            <th>İş</th>
            <th>Dil</th>
            <th>Versiyon</th>
            <th>Oluşturulma</th>
            <th>Explorer Konumu</th>
          </tr>
        </thead>
        <tbody>
          {(documents || []).map((document) => (
            <tr key={document.id}>
              <td>{document.type === "cover_letter" ? "Cover Letter" : "CV"}</td>
              <td>{document.metadata?.company || document.job_id.slice(0, 8)}</td>
              <td>{document.language.toUpperCase()}</td>
              <td>{document.version}</td>
              <td>{formatDate(document.created_at)}</td>
              <td><code className="artifact-path">{document.artifact_relative_path || "-"}</code></td>
            </tr>
          ))}
          {(!documents || documents.length === 0) && (
            <tr><td colSpan={6} className="muted">Henüz belge üretilmedi.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function EventsTable({ events }) {
  return (
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
              No pipeline events recorded yet.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function EventsTab({ events, error, refresh }) {
  return (
    <div className="panel">
      <Toolbar label="Pipeline event stream (monitor)" onRefresh={refresh} count={events?.length} />
      {error && <div className="error-banner">{error}</div>}
      <EventsTable events={events} />
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
      ? "Başvuru formları doldurulacak. CAPTCHA, MFA, belirsiz soru veya gönderim durumunda işlem durur; AUTO_SUBMIT kapalı olduğu sürece başvuru gönderilmez. Devam edilsin mi?"
      : `"${action.label}" işlemi başlatılsın mı?`;
    if (!window.confirm(prompt)) return;

    setRunningAction(action.id);
    setActionMessage("");
    try {
      const result = await fetchJson("/api/v1/pipeline/actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action.id, confirmed: true }),
      });
      setActionMessage(`${action.label} kuyruğa alındı (${result.correlation_id}).`);
      setTimeout(() => {
        jobsQ.refresh();
        applicationsQ.refresh();
        documentsQ.refresh();
        eventsQ.refresh();
      }, 1000);
    } catch (error) {
      setActionMessage(`${action.label} başlatılamadı: ${error.message}`);
    } finally {
      setRunningAction(null);
    }
  }, [applicationsQ, documentsQ, eventsQ, jobsQ]);

  const submitApplication = useCallback(async (application) => {
    const name = `${application.company} — ${application.title}`;
    if (!window.confirm(
      `${name} için Playwright formu doldurup gönder butonuna basacak. `
      + "CAPTCHA, MFA, giriş gereksinimi veya doğrulanmamış hukuki soru varsa işlem durur. Devam edilsin mi?"
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
      setActionMessage(`${name} için gönderim kuyruğa alındı (${result.correlation_id}).`);
      setTimeout(() => {
        applicationsQ.refresh();
        eventsQ.refresh();
      }, 1000);
    } catch (error) {
      setActionMessage(`${name} için gönderim başlatılamadı: ${error.message}`);
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
          onRun={runAction}
          runningAction={runningAction}
          actionMessage={actionMessage}
        />
      )}
      {tab === "Jobs" && <JobsTab jobs={jobsQ.data} error={jobsQ.error} refresh={jobsQ.refresh} />}
      {tab === "Applications" && (
        <ApplicationsTab
          applications={applicationsQ.data}
          error={applicationsQ.error}
          refresh={applicationsQ.refresh}
          onSubmit={submitApplication}
          submittingApplicationId={runningAction}
        />
      )}
      {tab === "Documents" && (
        <DocumentsTab
          documents={documentsQ.data}
          error={documentsQ.error}
          refresh={documentsQ.refresh}
        />
      )}
      {tab === "Events" && (
        <EventsTab events={eventsQ.data} error={eventsQ.error} refresh={eventsQ.refresh} />
      )}
      {tab === "Settings" && <SettingsTab status={statusQ.data} />}
    </main>
  );
}
