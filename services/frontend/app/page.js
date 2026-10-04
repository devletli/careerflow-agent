"use client";

import { useEffect, useState, useCallback } from "react";
import { fetchJson, formatDate, StatusPill, STRINGS } from "./lib";

const TABS = STRINGS.tabs;
const REFRESH_MS = 10000;
const THEME_KEY = "ai-job-agent-theme";

function usePersistentState(key, initial) {
  // SSR-safe: start from `initial` so server and client render identically,
  // then hydrate the stored value on mount (avoids React hydration mismatch).
  const [value, setValue] = useState(initial);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(`ai-job-agent-filter:${key}`);
      if (raw !== null) setValue(JSON.parse(raw));
    } catch {
      // storage unavailable: initial value stands
    }
  }, [key]);
  const set = useCallback(
    (next) => {
      setValue((prev) => {
        const resolved = typeof next === "function" ? next(prev) : next;
        try {
          localStorage.setItem(`ai-job-agent-filter:${key}`, JSON.stringify(resolved));
        } catch {
          // storage unavailable: state still applies for this session
        }
        return resolved;
      });
    },
    [key]
  );
  return [value, set];
}

function useDebouncedValue(value, delayMs = 350) {
  // Backend filtreleri (?q=) her tuşta değil, yazım durunca tetiklenir.
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

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
  const label = isDark ? STRINGS.themeLight : STRINGS.themeDark;
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={onToggle}
      aria-label={label}
      title={label}
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
    const tick = () => {
      if (!document.hidden) refresh();
    };
    const id = setInterval(tick, REFRESH_MS);
    const onVisible = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
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
        API {health ? health.status : STRINGS.statusUnknown}
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
      // Keep the last good data on error; surface the error banner only.
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    refresh();
    // Pause polling while the tab is hidden; refresh once on return.
    const tick = () => {
      if (!document.hidden) refresh();
    };
    const id = setInterval(tick, REFRESH_MS);
    const onVisible = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, ...deps]);

  return { data, error, loading, refresh };
}

function Toolbar({ label, onRefresh, count }) {
  return (
    <div className="toolbar">
      <span className="muted">
        {label}
        {typeof count === "number" ? ` — ${STRINGS.countShown.replace("{count}", count)}` : ""}
      </span>
      <button className="refresh-btn" onClick={onRefresh}>
        {STRINGS.refresh}
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
      <h3 style={{ marginTop: 0 }}>{STRINGS.pipelineControls}</h3>
      <p className="muted">{STRINGS.pipelineControlsDesc}</p>
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
              {runningAction === action.id ? STRINGS.queueing : action.label}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatLlmStatus(llm) {
  if (!llm || !llm.state) return STRINGS.statusUnknown;
  const model = llm.model ? ` (${llm.model})` : "";
  const reason = llm.reason ? ` — ${llm.reason}` : "";
  return `${llm.state}${model}${reason}`;
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
          <div className="label">{STRINGS.statJobs}</div>
        </div>
        <div className="stat-card">
          <div className="value">{appCount}</div>
          <div className="label">{STRINGS.statApplications}</div>
        </div>
        <div className="stat-card">
          <div className="value">{submitted}</div>
          <div className="label">{STRINGS.statSubmitted}</div>
        </div>
        <div className="stat-card">
          <div className="value">{blocked}</div>
          <div className="label">{STRINGS.statBlocked}</div>
        </div>
      </div>
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{STRINGS.automationConfig}</h3>
        {status ? (
          <div className="settings-grid">
            <div className="settings-item">
              <div className="label">{STRINGS.automationMode}</div>
              <div className="value">{status.automation_mode}</div>
            </div>
            <div className="settings-item">
              <div className="label">{STRINGS.autoSubmit}</div>
              <div className="value">{String(status.auto_submit)}</div>
            </div>
            <div className="settings-item">
              <div className="label">{STRINGS.minMatchScoreLabel}</div>
              <div className="value">{status.min_match_score}</div>
            </div>
            <div className="settings-item">
              <div className="label">{STRINGS.llmLabel}</div>
              <div className="value">{formatLlmStatus(status.llm_status)}</div>
            </div>
          </div>
        ) : (
          <p className="muted">{STRINGS.loadingStatus}</p>
        )}
      </div>
      <div className="panel" style={{ marginTop: 16 }}>
        <h3 style={{ marginTop: 0 }}>{STRINGS.latestEvents}</h3>
        <EventsTable events={(events || []).slice(0, 8)} loading={eventsLoading} />
      </div>
    </div>
  );
}

function JobsTab({ jobs, query, onQueryChange, error, loading, refresh }) {
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

function ApplicationsTab({ applications, query, onQueryChange, statusFilter, onStatusChange, minScore, onMinScoreChange, error, loading, refresh, onExecute, busyId }) {
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
              <td data-label={STRINGS.colStatus}><StatusPill status={a.status} /></td>
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

function DocumentsTab({ documents, query, onQueryChange, error, loading, refresh }) {
  // Liste: job+tur basina SON surum; eski surumler yalnizca detay sayfasinda.
  // Arama backend'de (?q=).
  const rows = (documents || []).filter((d) => d.is_latest);
  return (
    <div className="panel">
      <Toolbar label={STRINGS.docsToolbar} onRefresh={refresh} count={rows?.length} />
      <SearchBar value={query} onChange={onQueryChange} />
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
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={4} className="muted">{loading ? STRINGS.loading : STRINGS.noDocumentsYet}</td></tr>
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

function EventsTab({ events, query, onQueryChange, error, loading, refresh }) {
  // Arama backend'de (?q=).
  return (
    <div className="panel">
      <Toolbar label={STRINGS.latestEvents} onRefresh={refresh} count={events?.length} />
      <SearchBar value={query} onChange={onQueryChange} />
      {error && <div className="error-banner">{error}</div>}
      <EventsTable events={events} loading={loading} />
    </div>
  );
}

function SettingsTab({ status }) {
  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>{STRINGS.runtimeSettings}</h3>
      <p className="muted">
        {STRINGS.settingsHintA} <code>.env</code> {STRINGS.settingsHintB} <code>docker compose up -d</code>.
      </p>
      {status ? (
        <div className="settings-grid">
          <div className="settings-item">
            <div className="label">{STRINGS.colService}</div>
            <div className="value">{status.service}</div>
          </div>
          <div className="settings-item">
            <div className="label">{STRINGS.colVersion}</div>
            <div className="value">{status.version}</div>
          </div>
          <div className="settings-item">
            <div className="label">{STRINGS.automationMode}</div>
            <div className="value">{status.automation_mode}</div>
          </div>
          <div className="settings-item">
            <div className="label">{STRINGS.autoSubmit}</div>
            <div className="value">{String(status.auto_submit)}</div>
          </div>
          <div className="settings-item">
            <div className="label">{STRINGS.minMatchScoreLabel}</div>
            <div className="value">{status.min_match_score}</div>
          </div>
          <div className="settings-item">
            <div className="label">{STRINGS.llmLabel}</div>
            <div className="value">{formatLlmStatus(status.llm_status)}</div>
          </div>
        </div>
      ) : (
        <p className="muted">{STRINGS.loading}</p>
      )}
    </div>
  );
}

function tabFromHash() {
  if (typeof window === "undefined") return "Overview";
  const slug = window.location.hash.replace(/^#/, "").toLowerCase();
  return TABS.find((t) => t.toLowerCase() === slug) || "Overview";
}

export default function Home() {
  // SSR renders "Overview"; the hash is applied on mount so server and
  // client HTML match (no hydration mismatch).
  const [tab, setTab] = useState("Overview");
  const [runningAction, setRunningAction] = useState(null);
  const [actionMessage, setActionMessage] = useState("");
  const { health } = useHealth();
  const { theme, toggle } = useTheme();

  // Active tab is derived from the URL hash so dashboard views are
  // deep-linkable (e.g. /#applications); nav itself comes from TABS.
  useEffect(() => {
    setTab(tabFromHash());
    const onHash = () => setTab(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const selectTab = useCallback((t) => {
    setTab(t);
    try {
      window.location.hash = t.toLowerCase();
    } catch {
      // non-browser render: state update above is enough
    }
  }, []);
  // Filtre state'leri burada tutulur: hem localStorage'da kalici (sekme
  // degisiminde sifirlanmaz) hem de backend ?q=/status/min_score
  // parametrelerine debounce ile baglanir.
  const [jobsQuery, setJobsQuery] = usePersistentState("jobs.query", "");
  const [appsQuery, setAppsQuery] = usePersistentState("applications.query", "");
  const [appsStatus, setAppsStatus] = usePersistentState("applications.status", "");
  const [appsMinScore, setAppsMinScore] = usePersistentState("applications.minScore", "");
  const [docsQuery, setDocsQuery] = usePersistentState("documents.query", "");
  const [eventsQuery, setEventsQuery] = usePersistentState("events.query", "");

  const dJobsQuery = useDebouncedValue(jobsQuery).trim();
  const dAppsQuery = useDebouncedValue(appsQuery).trim();
  const dDocsQuery = useDebouncedValue(docsQuery).trim();
  const dEventsQuery = useDebouncedValue(eventsQuery).trim();
  const qParam = (v) => (v ? `&q=${encodeURIComponent(v)}` : "");
  const appsScoreParam =
    appsMinScore !== "" && !Number.isNaN(Number(appsMinScore))
      ? `&min_score=${encodeURIComponent(appsMinScore)}`
      : "";
  const appsStatusParam = appsStatus ? `&status=${encodeURIComponent(appsStatus)}` : "";

  const statusQ = usePolling("/api/v1/status");
  const jobsQ = usePolling(`/api/v1/jobs?limit=100${qParam(dJobsQuery)}`);
  const applicationsQ = usePolling(
    `/api/v1/applications?limit=100${qParam(dAppsQuery)}${appsStatusParam}${appsScoreParam}`
  );
  const documentsQ = usePolling(`/api/v1/documents?limit=100${qParam(dDocsQuery)}`);
  const eventsQ = usePolling(`/api/v1/events?limit=50${qParam(dEventsQuery)}`);

  const runAction = useCallback(async (action) => {
    const requiresExtraWarning = action.id === "fill_applications";
    const prompt = requiresExtraWarning
      ? STRINGS.confirmFill
      : STRINGS.confirmStart.replace("{label}", action.label);
    if (!window.confirm(prompt)) return;

    setRunningAction(action.id);
    setActionMessage("");
    try {
      // Faz 3B: UI onayina guvenilmez; browser aksiyonu icin sunucudan
      // tek kullanimlik token alinir ve ayni istekte tuketilir.
      let confirmationToken;
      if (action.id === "fill_applications" || action.id === "submit_application") {
        const conf = await fetchJson("/api/v1/confirmations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: action.id }),
        });
        confirmationToken = conf.confirmation_token;
      }
      const result = await fetchJson("/api/v1/pipeline/actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action.id, confirmed: true, confirmation_token: confirmationToken }),
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

  const executeApplication = useCallback(async (application, action) => {
    if (!application || !action) return;
    const name = `${application.company} — ${application.title}`;

    if (action === "submit") {
      if (!window.confirm(STRINGS.confirmSubmit.replace("{name}", name))) return;
      setRunningAction(application.id);
      setActionMessage("");
      try {
        // Faz 3B: tek kullanimlik sunucu tokeni olmadan submit kuyruga girmez.
        const conf = await fetchJson("/api/v1/confirmations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "submit", application_id: application.id }),
        });
        // Explicit semantic action: the backend validates state, duplicate
        // and automation-mode guards, then queues the browser submission.
        const result = await fetchJson(`/api/v1/applications/${application.id}/execute`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "submit", confirmation_token: conf.confirmation_token }),
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
      return;
    }

    // prepare / retry / continue go through the explicit per-application endpoint
    // so the backend receives the semantic action (not an implicit submit).
    setRunningAction(application.id);
    setActionMessage("");
    try {
      const result = await fetchJson(`/api/v1/applications/${application.id}/execute`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      if (action === "continue" && result.manual_steps) {
        setActionMessage(result.manual_steps.join(" "));
      } else {
        setActionMessage(`${action} accepted for ${name} (status: ${result.status}).`);
      }
      setTimeout(() => {
        applicationsQ.refresh();
        eventsQ.refresh();
      }, 1000);
    } catch (error) {
      setActionMessage(`Could not run ${action} for ${name}: ${error.message}`);
    } finally {
      setRunningAction(null);
    }
  }, [applicationsQ, eventsQ]);

  return (
    <main className="app-shell">
      <div className="app-header">
        <h1>{STRINGS.appTitle}</h1>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <HealthBadges health={health} />
          <ThemeToggle theme={theme} onToggle={toggle} />
        </div>
      </div>

      <div className="tabs" role="tablist" aria-label={STRINGS.appTitle}>
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            aria-current={tab === t ? "page" : undefined}
            className={`tab ${tab === t ? "active" : ""}`}
            onClick={() => selectTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="tab-body">
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
      {tab === "Jobs" && <JobsTab jobs={jobsQ.data} query={jobsQuery} onQueryChange={setJobsQuery} error={jobsQ.error} loading={jobsQ.loading} refresh={jobsQ.refresh} />}
      {tab === "Applications" && (
        <ApplicationsTab
          applications={applicationsQ.data}
          query={appsQuery}
          onQueryChange={setAppsQuery}
          statusFilter={appsStatus}
          onStatusChange={setAppsStatus}
          minScore={appsMinScore}
          onMinScoreChange={setAppsMinScore}
          error={applicationsQ.error}
          loading={applicationsQ.loading}
          refresh={applicationsQ.refresh}
          onExecute={executeApplication}
          busyId={runningAction}
        />
      )}
      {tab === "Documents" && (
        <DocumentsTab
          documents={documentsQ.data}
          query={docsQuery}
          onQueryChange={setDocsQuery}
          error={documentsQ.error}
          loading={documentsQ.loading}
          refresh={documentsQ.refresh}
        />
      )}
      {tab === "Events" && (
        <EventsTab events={eventsQ.data} query={eventsQuery} onQueryChange={setEventsQuery} error={eventsQ.error} loading={eventsQ.loading} refresh={eventsQ.refresh} />
      )}
      {tab === "Settings" && <SettingsTab status={statusQ.data} />}
      </div>
    </main>
  );
}
