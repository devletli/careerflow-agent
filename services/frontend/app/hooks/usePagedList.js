// Ortak cursor-sayfalama kancası: tüm sekmeler bunu kullanır.
// fetchPage fonksiyon kimliği değişse de efekt yeniden başlamaz (sonsuz
// istek döngüsü yok); polling kancanın içindedir (cursor sabit, sekme
// gizliyken durur, hata olunca son veri korunur). Filtre değişince
// {key, stack} ile 1. sayfaya dönülür (ayrı reset efekti yok).
// Toplu seçim bu kancada DEĞİL üst bileşende id kümesi olarak tutulur
// (polling'den sonra korunur).
import { useEffect, useRef, useState } from "react";

export function usePagedList(fetchPage, filtersKey, { pollMs = 10000 } = {}) {
  const fetchRef = useRef(fetchPage);
  fetchRef.current = fetchPage;
  const [nav, setNav] = useState({ key: filtersKey, stack: [null] });
  const stack = nav.key === filtersKey ? nav.stack : [null];
  const cursor = stack[stack.length - 1];
  const [data, setData] = useState({ items: [], next_cursor: null, total: 0 });
  const [error, setError] = useState(null);
  // refresh: mevcut sayfayı (cursor sabit) yeniden çeker; sayfa 1'e atmaz.
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    let timer;
    const load = async () => {
      if (typeof document === "undefined" || document.visibilityState === "visible") {
        try {
          const d = await fetchRef.current(cursor);
          if (alive) {
            setData(d);
            setError(null);
          }
        } catch (e) {
          if (alive) setError(e);
        }
      }
      if (alive) timer = setTimeout(load, pollMs);
    };
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [cursor, filtersKey, pollMs, tick]);

  return {
    ...data,
    error,
    page: stack.length,
    next: () => data.next_cursor && setNav({ key: filtersKey, stack: [...stack, data.next_cursor] }),
    prev: () => stack.length > 1 && setNav({ key: filtersKey, stack: stack.slice(0, -1) }),
    refresh: () => setTick((t) => t + 1),
  };
}
