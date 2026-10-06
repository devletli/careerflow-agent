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
  const jobsQ = usePolling(
    `/api/v1/jobs?limit=100${qParam(dJobsQuery)}${hideArchived ? "&exclude_archived=true" : ""}`
  );
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
        jobsQ.refresh();
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
  }, [deleteTarget, deletingId, jobsQ, applicationsQ, documentsQ, eventsQ]);

  const archiveJob = useCallback(async (job, userStatus) => {
    if (!job?.id || archivingId) return;
    setArchivingId(job.id);
    try {
      await fetchJson(`/api/v1/jobs/${job.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_status: userStatus }),
      });
      jobsQ.refresh();
    } catch (error) {
      setActionMessage(`${STRINGS.archiveFailed} ${error.message}`);
    } finally {
      setArchivingId(null);
    }
  }, [archivingId, jobsQ]);

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
          jobs={jobsQ.data}
          applications={applicationsQ.data}
          events={eventsQ.data}
          eventsLoading={eventsQ.loading}
          onRun={runAction}
          runningAction={runningAction}
          actionMessage={actionMessage}
        />
      )}
      {tab === "Jobs" && <JobsTab jobs={jobsQ.data} query={jobsQuery} onQueryChange={setJobsQuery} error={jobsQ.error} loading={jobsQ.loading} refresh={jobsQ.refresh} onDelete={(j) => requestDelete("job", j)} deletingId={deletingId} onArchive={archiveJob} archivingId={archivingId} hideArchived={hideArchived} onHideArchivedChange={setHideArchived} />}
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
          busyId={runningAction || deletingId}
          onDelete={(a) => requestDelete("application", a)}
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
