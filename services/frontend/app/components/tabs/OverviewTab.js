"use client";

import { STRINGS } from "../../lib";
import { EventsTable, formatLlmStatus } from "../shared";

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

export default function OverviewTab({ status, jobs, applications, events, eventsLoading, onRun, runningAction, actionMessage }) {
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
