// Small client-side fetch helper for the dashboard.
// All requests go through Next.js rewrites (see next.config.js), so the
// browser only ever talks to this frontend's own origin.
export async function fetchJson(path, options = {}) {
  const res = await fetch(path, { cache: "no-store", ...options });
  if (!res.ok) {
    throw new Error(`Request to ${path} failed with status ${res.status}`);
  }
  return res.json();
}

export function formatDate(iso) {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function StatusPill({ status }) {
  if (!status) return <span className="status-pill status-UNKNOWN">UNKNOWN</span>;
  return <span className={`status-pill status-${status}`}>{status}</span>;
}

// Dashboard strings (T7 i18n). Default locale comes from the
// NEXT_PUBLIC_LOCALE environment variable ("en" unless set to "tr").
// Add new user-facing text to services/frontend/i18n/{en,tr}.json,
// never as hardcoded literals in page components.
import enStrings from "../i18n/en.json";
import trStrings from "../i18n/tr.json";

const _locale = (typeof process !== "undefined" && process.env.NEXT_PUBLIC_LOCALE) || "en";

export const LOCALE = String(_locale).toLowerCase().startsWith("tr") ? "tr" : "en";
export const STRINGS = LOCALE === "tr" ? trStrings : enStrings;
