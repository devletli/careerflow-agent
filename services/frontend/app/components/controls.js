"use client";

import { STRINGS } from "../lib";

export function Toolbar({ label, onRefresh, count }) {
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

export function SearchBar({ value, onChange, statusValue, onStatusChange, statuses, minScore, onMinScoreChange, showScore }) {
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

export function distinctStatuses(rows) {
  return [...new Set((rows || []).map((r) => r.status).filter(Boolean))].sort();
}
