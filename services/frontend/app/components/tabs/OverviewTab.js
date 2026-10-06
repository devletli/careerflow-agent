"use client";

import { useEffect, useState } from "react";
import { fetchJson, STRINGS } from "../../lib";
import { EventsTable, formatLlmStatus } from "../shared";

function dayKey(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function FollowUpPanel({ applications }) {
  const [upcoming, setUpcoming] = useState([]);
  const [overdueFetch, setOverdueFetch] = useState([]);
  useEffect(() => {
    let cancelled = false;
    // Refetch when the polled applications change so newly scheduled
    // interviews / due dates appear without a full page reload. Overdue is
    // also fetched server-side so items beyond the first 100 applications
    // still surface here.
    Promise.all([
      fetchJson("/api/v1/interviews?upcoming=true&limit=20").catch(() => []),
      fetchJson("/api/v1/applications?overdue=true&limit=50").catch(() => []),
    ]).then(([ivRows, overdueRows]) => {
      if (cancelled) return;
      setUpcoming(ivRows || []);
      setOverdueFetch(overdueRows || []);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [applications]);
  const now = new Date();
  const today = dayKey(now.toISOString());
  const groups = { overdue: [], today: [], upcomingActions: [] };
  const seen = new Set();
  for (const a of [...(overdueFetch || []), ...(applications || [])]) {
    if (!a.next_action_due_at || seen.has(a.id)) continue;
    seen.add(a.id);
    const due = new Date(a.next_action_due_at);
    const entry = { id: a.id, label: `${a.company} — ${a.title}`, detail: a.next_action, due: a.next_action_due_at };
    if (due < now) { groups.overdue.push(entry); }
    else if (dayKey(a.next_action_due_at) === today) groups.today.push(entry);
    else groups.upcomingActions.push(entry);
  }
  const empty = groups.overdue.length === 0 && groups.today.length === 0
    && groups.upcomingActions.length === 0 && upcoming.length === 0;
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>{STRINGS.followUp}</h3>
      {empty && <p className="muted">{STRINGS.noFollowUps}</p>}
      {groups.overdue.length > 0 && (
        <div className="settings-item">
          <div className="label">⚠ {STRINGS.overdue}</div>
          <div className="value">
            {groups.overdue.map((g) => (
              <div key={g.id}><a className="link" href={`/applications/${g.id}`}>{g.label}</a> — {g.detail || ""} ({g.due.slice(0, 10)})</div>
            ))}
          </div>
        </div>
      )}
      {groups.today.length > 0 && (
        <div className="settings-item">
          <div className="label">{STRINGS.dueToday}</div>
          <div className="value">
            {groups.today.map((g) => (
              <div key={g.id}><a className="link" href={`/applications/${g.id}`}>{g.label}</a> — {g.detail || ""}</div>
            ))}
          </div>
        </div>
      )}
      {groups.upcomingActions.length > 0 && (
        <div className="settings-item">
          <div className="label">{STRINGS.upcoming}</div>
          <div className="value">
            {groups.upcomingActions.map((g) => (
              <div key={g.id}><a className="link" href={`/applications/${g.id}`}>{g.label}</a> — {g.detail || ""} ({g.due.slice(0, 10)})</div>
            ))}
          </div>
        </div>
      )}
      {upcoming.length > 0 && (
        <div className="settings-item">
          <div className="label">{STRINGS.upcomingInterviews}</div>
          <div className="value">
            {upcoming.map((iv) => (
              <div key={iv.id}><a className="link" href={`/applications/${iv.application_id}`}>{iv.company} — {iv.title}</a> — {iv.round || ""} ({(iv.scheduled_at || "").slice(0, 16).replace("T", " ")})</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const ACTIONS = STRINGS.actions;

function ActionPanel({ onRun, runningAction, actionMessage }) {
  return (
    <details className="panel" style={{ marginBottom: 16 }}>
      <summary style={{ cursor: "pointer", fontWeight: 600 }}>{STRINGS.advanced}</summary>
      <h3 style={{ marginTop: 8 }}>{STRINGS.pipelineControls}</h3>
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
    </details>
  );
}

function ScorePanel({ onNavigate }) {
  const [stats, setStats] = useState(null);
  useEffect(() => {
    let cancelled = false;
    fetchJson("/api/v1/stats/score-distribution")
      .then((d) => { if (!cancelled) setStats(d); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);
  if (!stats) return null;
  const max = Math.max(1, ...(stats.buckets || []).map((b) => b.count));
  const qualified = (stats.bands || {}).QUALIFIED || 0;
  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <h3 style={{ marginTop: 0 }}>{STRINGS.scoreDist}</h3>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 64 }}>
        {(stats.buckets || []).map((b) => (
          <div
            key={b.from}
            title={`${b.from}–${b.to}: ${b.count}`}
            style={{ flex: 1, height: `${Math.round((b.count / max) * 56) + 4}px`, background: "var(--accent)" }}
          />
        ))}
      </div>
      {qualified === 0 && (
        <p className="muted">
          {(STRINGS.scoreEmpty || "")
            .replace("{max}", stats.max_score ?? "–")
            .replace("{threshold}", stats.threshold ?? "–")}{" "}
          <button className="link" onClick={() => onNavigate(1, { band: "REVIEW" })}>
            {STRINGS.reviewList}
          </button>
        </p>
      )}
    </div>
  );
}
function InboxCards({ inbox, onNavigate }) {
  // Sekme adları i18n'e göre değişir; TABS sırası sabittir (1=Jobs, 3=Applications).
  const cards = [
    { label: STRINGS.inboxNeedsYou, value: inbox?.needs_you, go: () => onNavigate(3, { status: "REQUIRES_HUMAN" }) },
    { label: STRINGS.inboxReady, value: inbox?.ready, go: () => onNavigate(3, { status: "READY_TO_SUBMIT" }) },
    { label: STRINGS.inboxFailed, value: inbox?.failed, go: () => onNavigate(3, { status: "FAILED" }) },
    { label: STRINGS.inboxToPrepare, value: inbox?.to_prepare, go: () => onNavigate(3, { status: "CREATED" }) },
    { label: STRINGS.inboxNewStrong, value: inbox?.new_strong_matches, go: () => onNavigate(1, { band: "QUALIFIED" }) },
  ];
  return (
    <div className="stat-grid" style={{ marginBottom: 16 }}>
      {cards.map((c) => (
        <button key={c.label} className="stat-card" onClick={c.go} style={{ cursor: "pointer", textAlign: "left" }}>
          <div className="value">{c.value ?? "–"}</div>
          <div className="label">{c.label}</div>
        </button>
      ))}
    </div>
  );
}

export default function OverviewTab({ status, applications, inbox, onNavigate, events, eventsLoading, onRun, runningAction, actionMessage }) {
  return (
    <div>
      <InboxCards inbox={inbox} onNavigate={onNavigate} />
      <ScorePanel onNavigate={onNavigate} />
      <FollowUpPanel applications={applications} />
      <ActionPanel onRun={onRun} runningAction={runningAction} actionMessage={actionMessage} />
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
