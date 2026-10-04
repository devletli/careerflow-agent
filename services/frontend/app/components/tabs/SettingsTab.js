"use client";

import { STRINGS } from "../../lib";
import { formatLlmStatus } from "../shared";

export default function SettingsTab({ status }) {
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
