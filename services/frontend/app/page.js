"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchJson, STRINGS } from "./lib";
import { HealthBadges, ThemeToggle } from "./components/chrome";
import MainNav, { TABS } from "./components/MainNav";
import OverviewTab from "./components/tabs/OverviewTab";
import JobsTab from "./components/tabs/JobsTab";
import DocumentsTab from "./components/tabs/DocumentsTab";
import ApplicationsTab from "./components/tabs/ApplicationsTab";
import EventsTab from "./components/tabs/EventsTab";
import SettingsTab from "./components/tabs/SettingsTab";
import { ConfirmDeleteDialog, deleteResource } from "./components/shared";
import {
  useDebouncedValue,
  useHealth,
  usePersistentState,
  usePolling,
  useTheme,
} from "./hooks/usePolling";
import { usePagedList } from "./hooks/usePagedList";

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
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [archivingId, setArchivingId] = useState(null);
  const [hideArchived, setHideArchived] = usePersistentState("jobs.hideArchived", false);
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
  const [jobsMinScore, setJobsMinScore] = usePersistentState("jobs.minScore", "");
  const [jobsBand, setJobsBand] = usePersistentState("jobs.band", "");
  const [jobsSource, setJobsSource] = usePersistentState("jobs.source", "");
  const [jobsOnlyNew, setJobsOnlyNew] = usePersistentState("jobs.onlyNew", false);
  const [appsQuery, setAppsQuery] = usePersistentState("applications.query", "");
  const [appsStatus, setAppsStatus] = usePersistentState("applications.status", "");
  const [appsMinScore, setAppsMinScore] = usePersistentState("applications.minScore", "");
  const [docsQuery, setDocsQuery] = usePersistentState("documents.query", "");
  const [eventsQuery, setEventsQuery] = usePersistentState("events.query", "");
  // Toplu seçim üst bileşendedir: polling ve sayfa değişiminden sağ çıkar.
  const [selectedJobIds, setSelectedJobIds] = usePersistentState("jobs.selected", []);
  const [preparing, setPreparing] = useState(false);
  const [prepareMessage, setPrepareMessage] = useState("");

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
  // Faz 5: Jobs tablosu cursor sayfalamalidir; 10sn polling tabloyu ve
  // cursor'i SIFIRLAMAZ. jobsMetaQ yalnizca ust ozet sayaclari gunceller,
  // sayfa verisi kullanici sayfa/filtre degistirene kadar sabit kalir.
  const jobsFilterParams = useCallback((cursor) => {
    let p = `limit=100${qParam(dJobsQuery)}`;
    if (jobsMinScore !== "" && !Number.isNaN(Number(jobsMinScore))) p += `&min_score=${encodeURIComponent(jobsMinScore)}`;
    if (jobsBand) p += `&band=${encodeURIComponent(jobsBand)}`;
    if (jobsSource) p += `&source=${encodeURIComponent(jobsSource)}`;
    if (jobsOnlyNew) p += `&recent_days=7`;
    if (hideArchived) p += `&exclude_archived=true`;
    if (cursor) p += `&cursor=${encodeURIComponent(cursor)}`;
    return p;
  }, [dJobsQuery, jobsMinScore, jobsBand, jobsSource, jobsOnlyNew, hideArchived]);
  const jobsMetaQ = usePolling(`/api/v1/jobs?${jobsFilterParams("")}&limit=1`);
  const [jobsList, setJobsList] = useState([]);
  const [jobsMeta, setJobsMeta] = useState({ total: 0, scored: 0, unscored: 0, next_cursor: null });
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsError, setJobsError] = useState(null);
  const [cursorStack, setCursorStack] = useState([null]);
  const fetchJobsPage = useCallback(async (cursor) => {
    setJobsLoading(true);
    try {
      const res = await fetchJson(`/api/v1/jobs?${jobsFilterParams(cursor)}`);
      const items = Array.isArray(res) ? res : (res.items || []);
      setJobsList(items);
      if (!Array.isArray(res)) {
        setJobsMeta({
          total: res.total ?? items.length,
          scored: res.scored ?? 0,
          unscored: res.unscored ?? 0,
          next_cursor: res.next_cursor ?? null,
        });
      }
      setJobsError(null);
    } catch (e) {
      // Son veri korunur; yalnizca hata bandi gosterilir.
      setJobsError(e.message);
    } finally {
      setJobsLoading(false);
    }
  }, [jobsFilterParams]);
  // Filtre degisince ilk sayfaya don (polling bunu tetiklemez).
  useEffect(() => {
    setCursorStack([null]);
    fetchJobsPage(null);
  }, [fetchJobsPage]);
  // Ozet sayaçlar polling ile güncellenir; tabloya dokunulmaz.
  useEffect(() => {
    const m = jobsMetaQ.data;
    if (m && !Array.isArray(m)) {
      setJobsMeta({
        total: m.total ?? 0,
        scored: m.scored ?? 0,
        unscored: m.unscored ?? 0,
        next_cursor: jobsMeta.next_cursor,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobsMetaQ.data]);
  const jobsRefresh = useCallback(() => {
    fetchJobsPage(cursorStack[cursorStack.length - 1] || null);
    jobsMetaQ.refresh();
  }, [fetchJobsPage, cursorStack, jobsMetaQ]);
  const jobsNext = useCallback(() => {
    const next = jobsMeta.next_cursor;
    if (!next) return;
    setCursorStack((s) => [...s, next]);
    fetchJobsPage(next);
  }, [jobsMeta.next_cursor, fetchJobsPage]);
  const jobsPrev = useCallback(() => {
    if (cursorStack.length <= 1) return;
    const prev = cursorStack[cursorStack.length - 2] || null;
    setCursorStack((s) => s.slice(0, -1));
    fetchJobsPage(prev);
  }, [cursorStack, fetchJobsPage]);
  const applicationsQ = usePagedList(
    useCallback(
      async (cursor) => {
        let url = `/api/v1/applications?limit=50${qParam(dAppsQuery)}${appsStatusParam}${appsScoreParam}`;
        if (cursor) url += `&cursor=${encodeURIComponent(cursor)}`;
        const res = await fetchJson(url);
        if (Array.isArray(res)) return { items: res, next_cursor: null, total: res.length };
        return { items: res.items || [], next_cursor: res.next_cursor ?? null, total: res.total ?? 0 };
      },
      [dAppsQuery, appsStatusParam, appsScoreParam]
    ),
    `apps:${dAppsQuery}:${appsStatus}:${appsMinScore}`
  );
  const documentsQ = usePagedList(
    useCallback(
      async (cursor) => {
        let url = `/api/v1/documents?limit=50${qParam(dDocsQuery)}`;
        if (cursor) url += `&cursor=${encodeURIComponent(cursor)}`;
        const res = await fetchJson(url);
        if (Array.isArray(res)) return { items: res, next_cursor: null, total: res.length };
        return { items: res.items || [], next_cursor: res.next_cursor ?? null, total: res.total ?? 0 };
      },
      [dDocsQuery]
    ),
    `docs:${dDocsQuery}`
  );
  const eventsQ = usePolling(`/api/v1/events?limit=50${qParam(dEventsQuery)}`);
  const inboxQ = usePolling("/api/v1/inbox");

  // Eylem kutusu kartları: ilgili filtreli listeye gider (TABS sırası sabittir).
  const navigateInbox = useCallback((tabIdx, patch) => {
    selectTab(TABS[tabIdx]);
    if (patch?.status !== undefined) setAppsStatus(patch.status);
    if (patch?.band !== undefined) setJobsBand(patch.band);
  }, [selectTab, setAppsStatus, setJobsBand]);

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
        jobsRefresh();
        applicationsQ.refresh();
        documentsQ.refresh();
        eventsQ.refresh();
      }, 1000);
    } catch (error) {
      setActionMessage(`Could not start ${action.label}: ${error.message}`);
    } finally {
      setRunningAction(null);
    }
  }, [applicationsQ, documentsQ, eventsQ, jobsRefresh]);

  const executeApplication = useCallback(async (application, action) => {    if (!application || !action) return;
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

  const requestDelete = useCallback((kind, item) => {
    if (!item?.id || deletingId) return;
    setDeleteTarget({ kind, item });
  }, [deletingId]);

  const cancelDelete = useCallback(() => {
    if (deletingId) return;
    setDeleteTarget(null);
  }, [deletingId]);

  const confirmDelete = useCallback(async () => {
    if (!deleteTarget?.item?.id || deletingId) return;
    const { kind, item } = deleteTarget;
    const path =
      kind === "job"
        ? `/api/v1/jobs/${item.id}`
        : kind === "application"
          ? `/api/v1/applications/${item.id}`
          : `/api/v1/documents/${item.id}`;
    setDeletingId(item.id);
    try {
      await deleteResource(path);
      setDeleteTarget(null);
      if (kind === "job") {
        jobsRefresh();
        applicationsQ.refresh();
        documentsQ.refresh();
        eventsQ.refresh();
      } else if (kind === "application") {
        applicationsQ.refresh();
        documentsQ.refresh();
        eventsQ.refresh();
      } else {
        documentsQ.refresh();
        applicationsQ.refresh();
      }
    } catch (error) {
      setActionMessage(`${STRINGS.deleteFailed} ${error.message}`);
    } finally {
      setDeletingId(null);
    }
  }, [deleteTarget, deletingId, jobsRefresh, applicationsQ, documentsQ, eventsQ]);

  const toggleSelectJob = useCallback((id) => {
    setSelectedJobIds((prev) => {
      const set = new Set(prev || []);
      if (set.has(id)) set.delete(id);
      else set.add(id);
      return [...set];
    });
  }, [setSelectedJobIds]);

  const toggleSelectPage = useCallback((pageIds, allSelected) => {
    setSelectedJobIds((prev) => {
      const set = new Set(prev || []);
      if (allSelected) {
        for (const id of pageIds) set.delete(id);
      } else {
        for (const id of pageIds) set.add(id);
      }
      return [...set].slice(0, 200);
    });
  }, [setSelectedJobIds]);

  // Toplu "Hazırla": yalnızca /prepare ucu; fill/submit bu akışa girmez.
  const prepareSelected = useCallback(async () => {
    const ids = selectedJobIds || [];
    if (ids.length === 0 || ids.length > 20 || preparing) return;
    if (!window.confirm((STRINGS.confirmPrepare || "").replace("{count}", ids.length))) return;
    setPreparing(true);
    setPrepareMessage("");
    try {
      const byId = new Map((jobsList || []).map((j) => [j.id, j]));
      const includeReview = ids.some((id) => byId.get(id)?.qualification_status === "REVIEW");
      const result = await fetchJson("/api/v1/jobs/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_ids: ids.slice(0, 20), include_review: includeReview }),
      });
      const accepted = (result.results || []).filter((r) => r.result === "accepted").length;
      setPrepareMessage(`${accepted}/${(result.results || []).length}`);
      setSelectedJobIds([]);
      jobsRefresh();
    } catch (error) {
      setPrepareMessage(error.message);
    } finally {
      setPreparing(false);
    }
  }, [selectedJobIds, preparing, jobsList, setSelectedJobIds, jobsRefresh]);

  const archiveJob = useCallback(async (job, userStatus) => {
    if (!job?.id || archivingId) return;
    setArchivingId(job.id);
    try {
      await fetchJson(`/api/v1/jobs/${job.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_status: userStatus }),
      });
      jobsRefresh();
    } catch (error) {
      setActionMessage(`${STRINGS.archiveFailed} ${error.message}`);
    } finally {
      setArchivingId(null);
    }
  }, [archivingId, jobsRefresh]);

  const deleteDialog = deleteTarget ? {
    job: { title: STRINGS.confirmDeleteJob, message: STRINGS.deleteJobDescription },
    application: { title: STRINGS.confirmDeleteApplication, message: STRINGS.deleteApplicationDescription },
    document: { title: STRINGS.confirmDeleteDocument, message: STRINGS.deleteDocumentDescription },
  }[deleteTarget.kind] : null;

  return (
    <main className="app-shell">
      <div className="app-header">
        <h1>{STRINGS.appTitle}</h1>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <HealthBadges health={health} />
          <ThemeToggle theme={theme} onToggle={toggle} />
        </div>
      </div>

      <MainNav active={tab} onSelect={selectTab} />

      <div className="tab-body">
      {tab === "Overview" && (
        <OverviewTab
          status={statusQ.data}
          applications={applicationsQ.items}
          inbox={inboxQ.data}
          onNavigate={navigateInbox}
          events={eventsQ.data}
          eventsLoading={eventsQ.loading}
          onRun={runAction}
          runningAction={runningAction}
          actionMessage={actionMessage}
        />
      )}
      {tab === "Jobs" && (
        <JobsTab
          jobs={jobsList}
          jobsMeta={jobsMeta}
          query={jobsQuery}
          onQueryChange={setJobsQuery}
          minScore={jobsMinScore}
          onMinScoreChange={setJobsMinScore}
          band={jobsBand}
          onBandChange={setJobsBand}
          source={jobsSource}
          onSourceChange={setJobsSource}
          onlyNew={jobsOnlyNew}
          onOnlyNewChange={setJobsOnlyNew}
          error={jobsError || jobsMetaQ.error}
          loading={jobsLoading}
          refresh={jobsRefresh}
          onNext={jobsNext}
          onPrev={jobsPrev}
          hasNext={Boolean(jobsMeta.next_cursor)}
          hasPrev={cursorStack.length > 1}
          page={cursorStack.length}
          onDelete={(j) => requestDelete("job", j)}
          deletingId={deletingId}
          onArchive={archiveJob}
          archivingId={archivingId}
          hideArchived={hideArchived}
          onHideArchivedChange={setHideArchived}
          selectedIds={selectedJobIds}
          onToggleSelect={toggleSelectJob}
          onToggleSelectPage={toggleSelectPage}
          preparing={preparing}
          prepareMessage={prepareMessage}
          onPrepare={prepareSelected}
        />
      )}
      {tab === "Applications" && (
        <ApplicationsTab
          applications={applicationsQ.items}
          total={applicationsQ.total}
          query={appsQuery}
          onQueryChange={setAppsQuery}
          statusFilter={appsStatus}
          onStatusChange={setAppsStatus}
          minScore={appsMinScore}
          onMinScoreChange={setAppsMinScore}
          error={applicationsQ.error?.message || applicationsQ.error}
          loading={!applicationsQ.items?.length && !applicationsQ.error}
          refresh={applicationsQ.refresh}
          onNext={applicationsQ.next}
          onPrev={applicationsQ.prev}
          hasNext={Boolean(applicationsQ.next_cursor)}
          hasPrev={applicationsQ.page > 1}
          page={applicationsQ.page}
          onExecute={executeApplication}
          busyId={runningAction || deletingId}
          onDelete={(a) => requestDelete("application", a)}
        />
      )}
      {tab === "Documents" && (
        <DocumentsTab
          documents={documentsQ.items}
          total={documentsQ.total}
          query={docsQuery}
          onQueryChange={setDocsQuery}
          error={documentsQ.error?.message || documentsQ.error}
          loading={!documentsQ.items?.length && !documentsQ.error}
          refresh={documentsQ.refresh}
          onNext={documentsQ.next}
          onPrev={documentsQ.prev}
          hasNext={Boolean(documentsQ.next_cursor)}
          hasPrev={documentsQ.page > 1}
          page={documentsQ.page}
          onDelete={(d) => requestDelete("document", d)}
          deletingId={deletingId}
        />
      )}
      {tab === "Events" && (
        <EventsTab events={eventsQ.data} query={eventsQuery} onQueryChange={setEventsQuery} error={eventsQ.error} loading={eventsQ.loading} refresh={eventsQ.refresh} />
      )}
      {tab === "Settings" && <SettingsTab status={statusQ.data} />}
      </div>
      {actionMessage && <div className="action-message" role="status">{actionMessage}</div>}
      <ConfirmDeleteDialog
        open={Boolean(deleteTarget)}
        title={deleteDialog?.title || ""}
        message={deleteDialog?.message || ""}
        onCancel={cancelDelete}
        onConfirm={confirmDelete}
        loading={Boolean(deletingId)}
      />
    </main>
  );
}
