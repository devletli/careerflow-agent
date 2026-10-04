"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../lib";

export const REFRESH_MS = 10000;
export const THEME_KEY = "ai-job-agent-theme";

export function usePersistentState(key, initial) {
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

export function useDebouncedValue(value, delayMs = 350) {
  // Backend filtreleri (?q=) her tuşta değil, yazım durunca tetiklenir.
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

export function useTheme() {
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

export function useHealth() {
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

export function usePolling(path, deps = []) {
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
