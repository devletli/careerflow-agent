"use client";

import { STRINGS } from "../lib";

// Tek navigasyon kaynagi: sekme listesi i18n'den gelir, aktif sekme URL hash'inden.
export const TABS = STRINGS.tabs;

export default function MainNav({ active, onSelect }) {
  return (
    <div className="tabs" role="tablist" aria-label={STRINGS.appTitle}>
      {TABS.map((t) => (
        <button
          key={t}
          role="tab"
          aria-selected={active === t}
          aria-current={active === t ? "page" : undefined}
          className={`tab ${active === t ? "active" : ""}`}
          onClick={() => onSelect(t)}
        >
          {t}
        </button>
      ))}
    </div>
  );
}
